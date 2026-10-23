from typing import List, Dict, Tuple, Set, Any, Optional
from typing import OrderedDict as OrderedDictType
import json
import logging
import tempfile
from collections import OrderedDict
from os.path import join as pjoin

from py4j.java_gateway import JavaGateway, GatewayParameters, launch_gateway, CallbackServerParameters

from scienceworld.constants import BASEPATH, DEBUG_MODE, ID2TASK, JAR_PATH
from scienceworld.utils import infer_task, snake_case_deprecation_warning

logger = logging.getLogger(__name__)


class ScienceWorldEnv:
    """Python wrapper for the simulator written in Scala. The methods that are
    being wrapped can be found in simulator/src/main/scala/scienceworld/runtime/AgentInterface.scala.
    Please look at that for more information on the internals of the system.
    """

    def __init__(self, taskName: Optional[str] = None, serverPath: Optional[str] = None, envStepLimit: int = 100):
        '''Start the simulator. Sets up the interface between python and the JVM.
        Also does basic init stuff.
        :param taskName: The name of the task. Will be run through the infer_task method.
            Tasks can also be loaded by the load method.
        :param serverPath: The filepath to the server. By default, it is just scienceworld.jar.
        :param envStepLimit: The maximum number of steps taken in the environment. Defaults to 100.
        '''
        serverPath = serverPath or JAR_PATH  # Use the builtin jar.

        # Launch the server and connect to the JVM.
        # Launch Java side with dynamic port and get back the port on which the
        # server was bound to.
        if DEBUG_MODE:
            import sys
            import time
            port, proc = launch_gateway(
                classpath=serverPath, die_on_exit=True, cwd=BASEPATH,
                javaopts=['-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5005,quiet=y'],
                redirect_stdout=sys.stdout, redirect_stderr=sys.stderr, return_proc=True)
            logger.debug("Attach debugger within the next 10 seconds")
            time.sleep(10)  # Give time for user to attach debugger
        else:
            port, proc = launch_gateway(classpath=serverPath, die_on_exit=True, cwd=BASEPATH, return_proc=True)

        # Connect python side to Java side with Java dynamic port and start python
        # callback server with a dynamic port
        self._gateway = JavaGateway(
            gateway_parameters=GatewayParameters(auto_field=True, port=port),
            callback_server_parameters=CallbackServerParameters(port=0, daemonize=True),
            java_process=proc)

        # Retrieve the port on which the python callback server was bound to.
        python_port = self._gateway.get_callback_server().get_listening_port()

        # Tell the Java side to connect to the python callback server with the new
        # python port. Note that we use the java_gateway_server attribute that
        # retrieves the GatewayServer instance.
        self._gateway.java_gateway_server.resetCallbackClient(
            self._gateway.java_gateway_server.getCallbackClient().getAddress(),
            python_port)

        self.server = self._gateway.jvm.scienceworld.runtime.pythonapi.PythonInterface()
        logger.info("ScienceWorld server running on port %d", port)

        # Keep track of the last step score, to calculate reward from score
        self.lastStepScore = 0

        # Load the script
        self.taskName = taskName
        if taskName:
            self.load(taskName, 0, "")

        # Set the environment step limit
        self.envStepLimit = envStepLimit

        # Clear the run histories
        self.clear_run_histories()

        # By default, set that the gold path was not generated unless the user asked for it
        self.goldPathGenerated = False

        self._obj_tree_tempdir = tempfile.TemporaryDirectory()

    # Ask the simulator to load an environment from a script
    def load(self, taskName: str, variationIdx: int = 0, simplificationStr: str = "",
             generateGoldPath: bool = False) -> None:
        '''Load a valid task and its variations/simplifications, and set up the simulator
        and any task-specific properties (electrical, etc). Can optionally have the
        simulator generate a gold path. If it successfully does, it will set
        self.goldPathGenerated to True.

        :param taskName: The name of the task. Will be modified by the infer_task function.
        :param variationIdx: The index for the specific variation to use. Default is 0.
        :param simplificationStr: The string of simplifications to use. Should be comma
            separated with no spaces. Defaults to "". For more, see get_possible_simplifications
        :param generateGoldPath: Boolean var to generate gold path or not. Defaults to False.
        '''
        # Check loading arguments.
        # Validate task name.
        taskName = infer_task(taskName)
        if taskName not in self.get_task_names():
            msg = "Unknown taskName: '{}'. ".format(taskName)
            msg += "Supported tasks are: {}".format(self.get_task_names())
            raise ValueError(msg)

        self.taskName = taskName

        # Validate simplification string.
        possible_simplifications = ["easy"] + self.get_possible_simplifications()
        for simplification in simplificationStr.split(","):
            if simplification and simplification not in possible_simplifications:
                msg = "Unknown simplification: '{}'. ".format(simplification)
                msg += "Supported simplifications are: {}".format(possible_simplifications)
                raise ValueError(msg)

        is_electrical_task = "power-component" in taskName or "conductivity" in taskName
        if is_electrical_task and "noElectricalAction" in simplificationStr:
            msg = "Invalid simplification. Task '{}' requires electrical actions but '--no-electrical' was provided."
            raise ValueError(msg.format(taskName))

        self.simplificationStr = simplificationStr
        self.variationIdx = variationIdx

        logger.info(f"Loading: {self.taskName} (variation: {self.variationIdx})" +
                    f" (simplifications: {self.simplificationStr})")
        self.server.load(self.taskName, self.variationIdx, self.simplificationStr, generateGoldPath)

        # Reset last step score (used to calculate reward from current-previous score)
        self.lastStepScore = 0

        # Keep track of whether the gold path was generated, to generate verbose error messages
        self.goldPathGenerated = generateGoldPath

    def reset(self) -> Tuple[str, Dict[str, Any]]:
        ''' Resets the simulator back to the first move (the output of "look around" is returned) '''

        self.server.reset()

        # Reset last step score (used to calculate reward from current-previous score)
        self.lastStepScore = 0

        # Make first move
        observation, score, isCompleted, info = self.step("look around")

        # Return a tuple that looks like the Jericho signature for reset
        return observation, info

    def close(self) -> None:
        self._gateway.shutdown()

        # According to https://github.com/py4j/py4j/issues/320#issuecomment-553599210
        # we need to send a newline to the process to make it exit.
        if self._gateway.java_process.poll() is None:
            self._gateway.java_process.stdin.write("\n".encode("utf-8"))
            self._gateway.java_process.stdin.flush()

    def __del__(self) -> None:
        self.close()

    # Simplifications
    def get_simplifications_used(self) -> str:
        ''' Gets the simplifications being used by the simulator. '''
        return self.server.getSimplificationsUsed()

    def get_possible_simplifications(self) -> List[str]:
        '''Gets the 6 possible simplifications. Those are:
            - teleportAction: Adds actions to teleport directly to any possible location
            - selfWateringFlowerPots: Flower pots will water themselves such that the plants won't die
            - openContainers: Containers are open by default
            - openDoors: Doors open are by default
            - noElectricalAction: Remove all `connect X to Y` actions to reduce the action space
            - easy: use all above simplifications
        '''
        return self.server.getPossibleSimplifications().split(", ")

    @property
    def tasks(self) -> OrderedDictType[str, str]:
        """ Get the supported tasks in ScienceWorld. """
        return OrderedDict(ID2TASK)

    @property
    def task_names(self) -> List[str]:
        ''' Get the name for the supported tasks in ScienceWorld. '''
        return list(ID2TASK.values())

    def get_task_names(self) -> List[str]:
        ''' Get the name for the supported tasks in ScienceWorld. '''
        return list(self.server.getTaskNames())

    def get_max_variations(self, task_name: str) -> int:
        ''' Get the maximum number of variations for the tasks. '''
        return self.server.getTaskMaxVariations(infer_task(task_name))

    # Get possible actions
    def get_possible_actions(self) -> List[str]:
        ''' Get all possible actions in the current environment state. '''
        return list(self.server.getPossibleActions())

    # Get possible actions (and also include the template IDs for those actions)
    def get_possible_actions_with_IDs(self) -> List[Dict[str, Any]]:
        ''' Get a list of dictionaries that map "action_example" to the action template and "template_id" to the id.'''
        jsonStr = self.server.getPossibleActionsWithIDs()
        data = json.loads(jsonStr)
        return data

    def get_possible_objects(self) -> List[str]:
        ''' Get a list of all observable objects '''
        return list(self.server.getPossibleObjects())

    # Get a list of object_ids to unique referents
    def get_possible_object_referent_LUT(self) -> Dict[str, str]:
        ''' Returns lookup table (dict) mapping object IDs to their referents. '''
        jsonStr = self.server.getPossibleObjectReferentLUTJSON()
        data = json.loads(jsonStr)
        return data

    # As above, but dictionary is referenced by object type ID
    def get_possible_object_referent_types_LUT(self) -> Dict[str, Dict[str, str]]:
        ''' Returns lookup table (dict) mapping object type IDs to a dict of all objects of that type. '''
        jsonStr = self.server.getPossibleObjectReferentTypesLUTJSON()
        data = json.loads(jsonStr)
        return data

    def get_valid_action_object_combinations(self) -> List[str]:
        ''' Get a list of all of the *valid* action-object combinations. '''
        return list(self.server.getValidActionObjectCombinations())

    def get_valid_action_object_combinations_with_templates(self) -> List[Dict[str, Any]]:
        ''' Returns list of dicts with keys "action", "template_id", and "obj_ids" '''
        jsonStr = self.server.getValidActionObjectCombinationsJSON()
        data = json.loads(jsonStr)
        return data['validActions']

    def get_all_object_types_LUTJSON(self) -> Dict[str, str]:
        ''' Returns look up table mapping object ids to type ids '''
        jsonStr = self.server.getAllObjectTypesLUTJSON()
        data = json.loads(jsonStr)
        return data

    # Get a LUT of {object_id: {type_id, referent:[]} } tuples
    def get_all_object_ids_types_referents_LUTJSON(self) -> Dict[str, Dict[str, Any]]:
        ''' Returns look up table mapping object ids to objects with keys "type_id" and "referents" '''
        jsonStr = self.server.getAllObjectIdsTypesReferentsLUTJSON()
        data = json.loads(jsonStr)
        return data

    # Get possible action/object combinations
    def get_possible_action_object_combinations(self) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        ''' Get all *possible* action-object combinations, including invalid ones. '''
        combinedJSON = self.server.getPossibleActionObjectCombinationsJSON()
        data = json.loads(combinedJSON)
        templates = data['templates']
        lookUpTable = data['lookUpTable']

        return (templates, lookUpTable)

    def get_object_types(self) -> Dict[str, int]:
        '''Get a dict mapping object names to the object id. The object name is the name
        of the actual file, for example "scienceworld.objects.containers.furniture.Chair".
        '''
        jsonStr = self.server.getObjectTypesLUTJSON()
        data = json.loads(jsonStr)
        return data

    def get_vocabulary(self) -> Set[str]:
        ''' Get all words that currently have some sort of meaning to the simulator. '''
        vocab = set()

        # Action vocabulary
        for actionStr in self.get_possible_actions():
            for word in actionStr.split(" "):
                vocab.add(word)

        # Object vocabulary (keep as compound nouns?)
        vocabObjects = self.get_possible_objects()
        vocab = vocab.union(set(vocabObjects))

        return vocab

    def get_num_moves(self) -> int:
        ''' Get the current number of moves. '''
        return self.server.getNumMoves()

    def get_task_description(self) -> str:
        ''' Get the description of the current task. '''
        return self.server.getTaskDescription()

    # Get the current game's task description
    def getObjectTree(self) -> Dict[str, Any]:
        msg = self.server.getObjectTree(self._obj_tree_tempdir.name)
        if msg:
            # Game is not initialized.
            raise RuntimeError(msg)

        with open(pjoin(self._obj_tree_tempdir.name, 'objectTree.json')) as f:
            payload = json.load(f)

        return payload

    #
    # History
    def get_run_history(self) -> Dict[str, Any]:
        ''' Get the run history '''
        historyStr = self.server.getRunHistoryJSON()
        jsonOut = json.loads(historyStr)
        return jsonOut

    # History saving (provides an API to do this, so it's consistent across agents)
    def store_run_history(self, episode_idx_key: int, notes: str) -> None:
        '''Store the run history, with notes.

        :param episode_idx_key: Episode index. Will be used as key.
        :param notes: Notes on the run.
        '''
        packed = {
            'episodeIdx': episode_idx_key,
            'notes': notes,
            'history': self.get_run_history()
        }

        self.runHistories[episode_idx_key] = packed

    def save_run_histories(self, filename_out_prefix: str) -> None:
        '''Save the run histories to a file.

        :param filename_out_prefix: The name of the file to write to.
        '''
        # Save history

        # Create verbose filename
        filenameOut = filename_out_prefix
        keys = sorted(self.runHistories.keys())
        if (len(keys) > 0):
            keyFirst = keys[0]
            keyLast = keys[-1]
            filenameOut += "-" + str(keyFirst) + "-" + str(keyLast)

        filenameOut += ".json"

        logger.info("* Saving run history (" + str(filenameOut) + ")...")

        with open(filenameOut, 'w') as outfile:
            json.dump(self.runHistories, outfile, sort_keys=True, indent=4)

    def get_run_history_size(self) -> int:
        ''' Get the size of the run history '''
        return len(self.runHistories)

    def clear_run_histories(self) -> None:
        ''' Clear the run histories. '''
        self.runHistories: Dict[int, Dict[str, Any]] = {}

    # A one-stop function to handle saving.
    def save_run_histories_buffer_if_full(self, filename_out_prefix: str,
                                          max_per_file: int = 1000, force_save: bool = False) -> None:
        '''One stop function for saving.

        If the histories buffer is full, saves to file and clears the buffer.

        :param filename_out_prefix: Name of the file to write to.
        :param max_per_file: The max number of histories per file. Defaults to 1000.
        :param force_save: Force the function to save, regardless of whether or not the
            buffer is full. Defaults to False.
        '''
        if ((self.get_run_history_size() >= max_per_file) or force_save):
            self.save_run_histories(filename_out_prefix)
            self.clear_run_histories()

    # Train/development/test sets
    def get_variations_train(self) -> List[int]:
        ''' Get the list of variations available for the training set. '''
        return list(self.server.getVariationsTrain())

    def get_variations_dev(self) -> List[int]:
        ''' Get the list of variations available for the development set. '''
        return list(self.server.getVariationsDev())

    def get_variations_test(self) -> List[int]:
        ''' Get the list of variations available for the testing set. '''
        return list(self.server.getVariationsTest())

    def get_random_variation_train(self) -> int:
        ''' Get a single random variation from those available for the training set. '''
        return self.server.getRandomVariationTrain()

    def get_random_variation_dev(self) -> int:
        ''' Get a single random variation from those available for the development set. '''
        return self.server.getRandomVariationDev()

    def get_random_variation_test(self) -> int:
        ''' Get a single random variation from those available for the testing set. '''
        return self.server.getRandomVariationTest()

    # Gold action sequence
    def get_gold_action_sequence(self) -> List[str]:
        '''Get the gold action sequence.
        The gold action sequence is a sequence of actions that leads to a winning state
        (there is no guarantee it is the optimal). This function returns that if it is generated.
        If it is not generated, it generates an error.
        '''
        if (self.goldPathGenerated):
            return list(self.server.getGoldActionSequence())
        else:
            return ["ERROR: Gold path was not generated.  Set `generateGoldPath` flag to true when calling load()."]

    # Step
    def step(self, input_str: str) -> Tuple[str, int, bool, Dict[str, Any]]:
        '''Take a step.

        This function takes one step in the typical state-action-reward cycle of RL.
        :param input_str: The input string supplied to the simulator from an agent.

        Returns the observation, reward, completion status, and infos dict consisting of:
        'moves', 'score', 'reward', 'look', 'inv', 'taskDesc', 'valid', 'variationIdx', 'taskName',
        and 'simplificationStr'.
        '''
        observation = self.server.step(input_str)
        score = int(round(100 * self.server.getScore()))        # Convert from 0-1 to 0-100
        isCompleted = self.server.getCompleted()
        numMoves = self.get_num_moves()

        # Calculate reward
        reward = score - self.lastStepScore         # Calculate reward (delta score) for this step
        self.lastStepScore = score                  # Store current score for reward calculation on the next step

        # If the number of moves exceeds the environment step limit, then set isCompleted to be true
        if (numMoves > self.envStepLimit):
            isCompleted = True

        # New: Handle this in the API rather than the agent
        # if the score is less than zero, then set the isCompleted flag to true.
        if (score < 0):
            isCompleted = True

        # Mirror of Jericho API
        infos = {
            'moves': numMoves,
            'score': score,
            'reward': reward,
            'look': self.look(),
            'inv': self.inventory(),
            'taskDesc': self.taskdescription(),
            'valid': self.get_valid_action_object_combinations(),
            'variationIdx': self.variationIdx,
            'taskName': self.taskName,
            'simplificationStr': self.simplificationStr,
        }

        return observation, reward, isCompleted, infos

    # Special actions that are "free" (consume zero time)
    def look(self) -> str:
        ''' Look around. This is a "free" action in that it consumes no time. '''
        observation = self.server.freeActionLook()
        return observation

    def inventory(self) -> str:
        ''' Check your inventory. This is a "free" action that consumes no time. '''
        observation = self.server.freeActionInventory()
        return observation

    def taskdescription(self) -> str:
        ''' Get the task description. This is a "free" action that consumes no time. '''
        observation = self.server.freeActionTaskDesc()
        return observation

    # Goal progress
    def get_goal_progress(self) -> str:
        ''' Get the progress to the goal. '''
        goalStr = self.server.getGoalProgressStr()
        return goalStr

    # ---------------- Camel Case Methods ---------------------
    # All of the wrapper methods for camel case, to avoid breaking projects.

    # Simplifications
    def getSimplificationsUsed(self) -> str:
        snake_case_deprecation_warning()

        return self.get_simplifications_used()

    def getPossibleSimplifications(self) -> List[str]:
        snake_case_deprecation_warning()

        return self.get_possible_simplifications()

    def getTaskNames(self) -> List[str]:
        """ Get the name for the supported tasks in ScienceWorld. """
        snake_case_deprecation_warning()

        return self.get_task_names()

    # Get the maximum number of variations for this task
    def getMaxVariations(self, taskName: str) -> int:
        snake_case_deprecation_warning()

        return self.get_max_variations(taskName)

    # Get possible actions
    def getPossibleActions(self) -> List[str]:
        snake_case_deprecation_warning()

        return self.get_possible_actions()

    # Get possible actions (and also include the template IDs for those actions)
    def getPossibleActionsWithIDs(self) -> List[Dict[str, Any]]:
        snake_case_deprecation_warning()

        return self.get_possible_actions_with_IDs()

    # Get possible objects
    def getPossibleObjects(self) -> List[str]:
        snake_case_deprecation_warning()

        return self.get_possible_objects()

    # Get a list of object_ids to unique referents
    def getPossibleObjectReferentLUT(self) -> Dict[str, str]:
        snake_case_deprecation_warning()

        return self.get_possible_object_referent_LUT()

    # As above, but dictionary is referenced by object type ID
    def getPossibleObjectReferentTypesLUT(self) -> Dict[str, Dict[str, str]]:
        snake_case_deprecation_warning()

        return self.get_possible_object_referent_types_LUT()

    # Get a list of *valid* agent-object combinations
    def getValidActionObjectCombinations(self) -> List[str]:
        snake_case_deprecation_warning()

        return self.get_valid_action_object_combinations()

    def getValidActionObjectCombinationsWithTemplates(self) -> List[Dict[str, Any]]:
        snake_case_deprecation_warning()

        return self.get_valid_action_object_combinations_with_templates()

    # Get a LUT of object_id to type_id
    def getAllObjectTypesLUTJSON(self) -> Dict[str, str]:
        snake_case_deprecation_warning()

        return self.get_all_object_types_LUTJSON()

    # Get a LUT of {object_id: {type_id, referent:[]} } tuples
    def getAllObjectIdsTypesReferentsLUTJSON(self) -> Dict[str, Dict[str, Any]]:
        snake_case_deprecation_warning()

        return self.get_all_object_ids_types_referents_LUTJSON()

    # Get possible action/object combinations
    def getPossibleActionObjectCombinations(self) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        snake_case_deprecation_warning()

        return self.get_possible_action_object_combinations()

    # Get a list of object types and their IDs
    def getObjectTypes(self) -> Dict[str, int]:
        snake_case_deprecation_warning()

        return self.get_object_types()

    # Get the vocabulary of the model (at the current state)
    def getVocabulary(self) -> Set[str]:
        snake_case_deprecation_warning()

        return self.get_vocabulary()

    def getNumMoves(self) -> int:
        snake_case_deprecation_warning()

        return self.get_num_moves()

    def getTaskDescription(self) -> str:
        snake_case_deprecation_warning()

        return self.get_task_description()

    def getRunHistory(self) -> Dict[str, Any]:
        snake_case_deprecation_warning()

        return self.get_run_history()

    def storeRunHistory(self, episodeIdxKey: int, notes: str) -> None:
        snake_case_deprecation_warning()

        self.store_run_history(episodeIdxKey, notes)

    def saveRunHistories(self, filenameOutPrefix: str) -> None:
        snake_case_deprecation_warning()

        self.save_run_histories(filenameOutPrefix)

    def getRunHistorySize(self) -> int:
        snake_case_deprecation_warning()

        return self.get_run_history_size()

    def clearRunHistories(self) -> None:
        snake_case_deprecation_warning()

        self.clear_run_histories()

    # A one-stop function to handle saving.
    def saveRunHistoriesBufferIfFull(self, filenameOutPrefix: str, maxPerFile: int = 1000,
                                     forceSave: bool = False) -> None:
        snake_case_deprecation_warning()

        self.save_run_histories_buffer_if_full(filenameOutPrefix, maxPerFile, forceSave)

    def getVariationsTrain(self) -> List[int]:
        snake_case_deprecation_warning()

        return self.get_variations_train()

    def getVariationsDev(self) -> List[int]:
        snake_case_deprecation_warning()

        return self.get_variations_dev()

    def getVariationsTest(self) -> List[int]:
        snake_case_deprecation_warning()

        return self.get_variations_test()

    def getRandomVariationTrain(self) -> int:
        snake_case_deprecation_warning()

        return self.get_random_variation_train()

    def getRandomVariationDev(self) -> int:
        snake_case_deprecation_warning()

        return self.get_random_variation_dev()

    def getRandomVariationTest(self) -> int:
        snake_case_deprecation_warning()

        return self.get_random_variation_test()

    def getGoldActionSequence(self) -> List[str]:
        snake_case_deprecation_warning()

        return self.get_gold_action_sequence()

    def getGoalProgressStr(self) -> str:
        snake_case_deprecation_warning()

        return self.get_goal_progress()


class BufferedHistorySaver:

    #
    # Constructor
    #
    def __init__(self, filenameOutPrefix: str):
        self.filenameOutPrefix = filenameOutPrefix

        # Clear the run histories
        self.clearRunHistories()

    #
    # Methods
    #

    # History saving (provides an API to do this, so it's consistent across agents)
    def storeRunHistory(self, runHistory: Dict[str, Any], episodeIdxKey: int, notes: str) -> None:
        packed = {
            'episodeIdx': episodeIdxKey,
            'notes': notes,
            'history': runHistory
        }

        self.runHistories[episodeIdxKey] = packed

    def saveRunHistories(self) -> None:
        # Save history

        # Create verbose filename
        filenameOut = self.filenameOutPrefix
        keys = sorted(self.runHistories.keys())
        if (len(keys) > 0):
            keyFirst = keys[0]
            keyLast = keys[-1]
            filenameOut += "-" + str(keyFirst) + "-" + str(keyLast)

        filenameOut += ".json"

        logger.info("* Saving run history ( " + str(filenameOut) + ")...")

        with open(filenameOut, 'w') as outfile:
            json.dump(self.runHistories, outfile, sort_keys=True, indent=4)

    def getRunHistorySize(self) -> int:
        return len(self.runHistories)

    def clearRunHistories(self) -> None:
        self.runHistories: Dict[int, Dict[str, Any]] = {}

    # A one-stop function to handle saving.
    def saveRunHistoriesBufferIfFull(self, maxPerFile: int = 1000, forceSave: bool = False) -> None:
        if ((self.getRunHistorySize() >= maxPerFile) or forceSave):
            self.saveRunHistories()
            self.clearRunHistories()
