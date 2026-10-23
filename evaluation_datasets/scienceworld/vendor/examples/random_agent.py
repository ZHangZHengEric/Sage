import time
import random
import argparse

from scienceworld import ScienceWorldEnv


def randomModel(args):
    """ Example random agent -- randomly picks an action at each step. """
    exitCommands = ["quit", "exit"]

    taskIdx = args['task_num']
    simplificationStr = args['simplification_str']
    numEpisodes = args['num_episodes']

    # Keep track of the agent's final scores
    finalScores = []

    # Initialize environment
    env = ScienceWorldEnv("", args['jar_path'], envStepLimit=args['env_step_limit'])

    taskNames = env.get_task_names()
    print("Task Names: " + str(taskNames))

    # Choose task
    taskName = taskNames[taskIdx]        # Just get first task
    # Load the task, we we have access to some extra accessors e.g. get_random_variation_train()
    env.load(taskName, 0, "")
    maxVariations = env.get_max_variations(taskName)
    print("Starting Task " + str(taskIdx) + ": " + taskName)
    time.sleep(2)

    # Start running episodes
    for episodeIdx in range(0, numEpisodes):
        # Pick a random task variation
        randVariationIdx = env.get_random_variation_train()
        env.load(taskName, randVariationIdx, simplificationStr)

        # Reset the environment
        initialObs, initialDict = env.reset()

        # Example accessors
        print("Possible actions: " + str(env.get_possible_actions()))
        print("Possible objects: " + str(env.get_possible_objects()))
        templates, lut = env.get_possible_action_object_combinations()
        print("Possible action/object combinations: " + str(templates))
        print("Object IDX to Object Referent LUT: " + str(lut))
        print("Task Name: " + taskName)
        print("Task Variation: " + str(randVariationIdx) + " / " + str(maxVariations))
        print("Task Description: " + str(env.get_task_description()))
        print("look: " + str(env.look()))
        print("inventory: " + str(env.inventory()))
        print("taskdescription: " + str(env.taskdescription()))

        score = 0.0
        isCompleted = False
        curIter = 0

        # Run one episode until we reach a stopping condition (including exceeding the maximum steps)
        userInputStr = "look around"        # First action
        while (userInputStr not in exitCommands) and (isCompleted is False):
            print("----------------------------------------------------------------")
            print("Step: " + str(curIter))

            # Send user input, get response
            observation, reward, isCompleted, info = env.step(userInputStr)
            score = info['score']

            print("\n>>> " + observation)
            print("Reward: " + str(reward))
            print("Score: " + str(score))
            print("isCompleted: " + str(isCompleted))

            # The environment will make isCompleted `True` when a stop condition
            # has happened, or the maximum number of steps is reached.
            if (isCompleted):
                break

            # Randomly select action

            # Any action (valid or not)
            # templates, lut = env.get_possible_action_object_combinations()
            # print("Possible action/object combinations: " + str(templates))
            # print("Object IDX to Object Referent LUT: " + str(lut))
            # randomTemplate = random.choice( templates )
            # print("Next random action: " + str(randomTemplate))
            # userInputStr = randomTemplate["action"]

            # Only valid actions
            validActions = env.get_valid_action_object_combinations_with_templates()
            randomAction = random.choice(validActions)
            print("Next random action: " + str(randomAction))
            userInputStr = randomAction["action"]

            print(list(lut.keys())[-1])

            # Sanitize input
            userInputStr = userInputStr.lower().strip()
            print("Choosing random action: " + str(userInputStr))

            # Keep track of the number of commands sent to the environment in this episode
            curIter += 1

        print("Goal Progress:")
        print(env.get_goal_progress())
        time.sleep(1)

        # Episode finished -- Record the final score
        finalScores.append(score)

        # Report progress of model
        print("Final score: " + str(score))
        print("isCompleted: " + str(isCompleted))

        # Save history -- and when we reach maxPerFile, export them to file
        filenameOutPrefix = args['output_path_prefix'] + str(taskIdx)
        env.store_run_history(episodeIdx, notes={'text': 'my notes here'})
        env.save_run_histories_buffer_if_full(filenameOutPrefix, max_per_file=args['max_episode_per_file'])

    # Episodes are finished -- manually save any last histories still in the buffer
    env.save_run_histories_buffer_if_full(filenameOutPrefix, max_per_file=args['max_episode_per_file'], force_save=True)

    # Show final episode scores to user
    # Clip negative scores to 0 for average calculation
    avg = sum([x for x in finalScores if x >= 0]) / len(finalScores)
    print("")
    print("---------------------------------------------------------------------")
    print(" Summary (Random Agent)")
    print(" Task " + str(taskIdx) + ": " + taskName)
    print(" Simplifications: " + str(simplificationStr))
    print("---------------------------------------------------------------------")
    print(" Episode scores: " + str(finalScores))
    print(" Average episode score: " + str(avg))
    print("---------------------------------------------------------------------")
    print("")

    print("Completed.")


def build_simplification_str(args):
    """ Build simplification_str from args. """
    simplifications = list()
    if args["teleport"]:
        simplifications.append("teleportAction")

    if args["self_watering_plants"]:
        simplifications.append("selfWateringFlowerPots")

    if args["open_containers"]:
        simplifications.append("openContainers")

    if args["open_doors"]:
        simplifications.append("openDoors")

    if args["no_electrical"]:
        simplifications.append("noElectricalAction")

    return args["simplifications_preset"] or ",".join(simplifications)


#
#   Parse command line arguments
#
def parse_args():
    desc = "Run a model that chooses random actions until successfully reaching the goal."
    parser = argparse.ArgumentParser(desc)
    parser.add_argument("--jar_path", type=str,
                        help="Path to the ScienceWorld jar file. Default: use builtin.")
    parser.add_argument("--task-num", type=int, default=13,
                        help="Specify the task number to play. Default: %(default)s")
    parser.add_argument("--var-num", type=int, default=0,
                        help="Specify the task variation number to play. Default: %(default)s")
    parser.add_argument("--env-step-limit", type=int, default=100,
                        help="Maximum number of steps per episode. Default: %(default)s")
    parser.add_argument("--num-episodes", type=int, default=5,
                        help="Number of episodes to play. Default: %(default)s")
    parser.add_argument("--seed", type=int,
                        help="Seed the random generator used for sampling random actions.")
    parser.add_argument("--output-path-prefix", default="save-histories",
                        help="Path prefix to use for saving episode transcripts. Default: %(default)s")
    parser.add_argument("--max-episode-per-file", type=int, default=1000,
                        help="Maximum number of episodes per transcript file. Default: %(default)s")

    simplification_group = parser.add_argument_group('Game simplifications')
    simplification_group.add_argument(
        "--simplifications-preset", choices=['easy'],
        help="Choose a preset among:\n"
             "'easy' (teleportAction,openDoors,selfWateringFlowerPots,noElectricalAction)."
    )
    simplification_group.add_argument("--teleport", action="store_true",
                                      help="Lets agents instantly move to any location.")
    simplification_group.add_argument("--self-watering-plants", action="store_true",
                                      help="Plants do not have to be frequently watered.")
    simplification_group.add_argument("--open-containers", action="store_true",
                                      help="All containers are opened by default.")
    simplification_group.add_argument("--open-doors", action="store_true",
                                      help="All doors are opened by default.")
    simplification_group.add_argument("--no-electrical", action="store_true",
                                      help="Remove the electrical actions (reduces the size of the action space).")

    args = parser.parse_args()
    params = vars(args)
    return params


def main():
    print("ScienceWorld 1.0 API Examples - Random Agent")
    # Parse command line arguments
    args = parse_args()
    random.seed(args["seed"])
    args["simplification_str"] = build_simplification_str(args)
    randomModel(args)


if __name__ == "__main__":
    main()
