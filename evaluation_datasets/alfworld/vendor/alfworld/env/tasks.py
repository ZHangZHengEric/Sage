import json
import numpy as np
from alfworld.gen.graph import graph_obj
from alfworld.gen.utils.game_util import get_objects_with_name_and_prop
from alfworld.env.reward import get_action


class BaseTask(object):
    '''
    base class for tasks
    '''

    def __init__(self, traj, env, args, reward_type='sparse', max_episode_length=2000):
        # settings
        self.traj = traj
        self.env = env
        self.args = args
        self.task_type = self.traj['task_type']
        self.max_episode_length = max_episode_length
        self.reward_type = reward_type
        self.step_num = 0
        self.num_subgoals = len(self.traj['plan']['high_pddl']) - 1  # ignore end noop
        self.goal_finished = False

        # internal states
        self.goal_idx = 0
        self.finished = -1

        # load navigation graph
        self.gt_graph = None
        self.load_nav_graph()

        # reward config
        self.reward_config = None
        self.load_reward_config(args.reward_config)
        self.strict = 'strict' in reward_type

        # prev state
        self.prev_state = self.env.last_event

    def load_reward_config(self, config_file):
        '''
        load json file with reward values
        '''
        with open(config_file, 'r') as rc:
            reward_config = json.load(rc)
        self.reward_config = reward_config

    def load_nav_graph(self):
        '''
        build navigation grid graph
        '''
        floor_plan = self.traj['scene']['floor_plan']
        scene_num = self.traj['scene']['scene_num']
        self.gt_graph = graph_obj.Graph(use_gt=True, construct_graph=True, scene_id=scene_num)

    def goal_satisfied(self, state):
        '''
        check if the overall task goal was satisfied.
        '''
        raise NotImplementedError

    def transition_reward(self, state):
        '''
        immediate reward given the current state
        '''
        reward = 0

        # goal completed
        if self.goal_finished:
            done = True
            return reward, done

        # get subgoal and action
        expert_plan = self.traj['plan']['high_pddl']
        action_type = expert_plan[self.goal_idx]['planner_action']['action']

        # subgoal reward
        if "dense" in self.reward_type:
            action = get_action(action_type, self.gt_graph, self.env, self.reward_config, self.strict)
            sg_reward, sg_done = action.get_reward(state, self.prev_state, expert_plan, self.goal_idx)
            reward += sg_reward
            if sg_done:
                self.finished += 1
                if self.goal_idx + 1 < self.num_subgoals:
                    self.goal_idx += 1

        # end task reward
        goal_finished = self.goal_satisfied(state)
        if goal_finished:
            reward += self.reward_config['Generic']['goal_reward']
            self.goal_finished = True

        # success reward
        if "success" in self.reward_type and self.env.last_event.metadata['lastActionSuccess']:
            reward += self.reward_config['Generic']['success']

        # failure reward
        if "failure" in self.reward_type and not self.env.last_event.metadata['lastActionSuccess']:
            reward += self.reward_config['Generic']['failure']

        # step penalty
        if self.step_num > len(self.traj['plan']['low_actions']):
            reward += self.reward_config['Generic']['step_penalty']

        # save event
        self.prev_state = self.env.last_event

        # step and check if max_episode_length reached
        self.step_num += 1
        done = self.goal_idx >= self.num_subgoals or self.step_num >= self.max_episode_length
        return reward, done

    def reset(self):
        '''
        Reset internal states
        '''
        self.goal_idx = 0
        self.finished = -1
        self.step_num = 0
        self.goal_finished = False

    def get_subgoal_idx(self):
        return self.finished

    def get_target(self, var):
        '''
        returns the object type of a task param
        '''
        return self.traj['pddl_params'][var] if self.traj['pddl_params'][var] is not None else None

    def get_targets(self):
        '''
        returns a dictionary of all targets for the task
        '''
        targets = {
            'object': self.get_target('object_target'),
            'parent': self.get_target('parent_target'),
            'toggle': self.get_target('toggle_target'),
            'mrecep': self.get_target('mrecep_target'),
        }

        # slice exception
        if 'object_sliced' in self.traj['pddl_params'] and self.traj['pddl_params']['object_sliced']:
            targets['object'] += 'Sliced'  # Change, e.g., "Apple" -> "AppleSliced" as pickup target.

        return targets


class PickAndPlaceSimpleTask(BaseTask):
    '''
    pick_and_place task
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def goal_satisfied(self, state):
        # check if any object of 'object' class is inside any receptacle of 'parent' class
        pcs = self.goal_conditions_met(state)
        return pcs[0] == pcs[1]

    def goal_conditions_met(self, state):
        ts = 1
        s = 0

        targets = self.get_targets()
        receptacles = get_objects_with_name_and_prop(targets['parent'], 'receptacle', state.metadata)
        pickupables = get_objects_with_name_and_prop(targets['object'], 'pickupable', state.metadata)

        # check if object needs to be sliced
        if 'Sliced' in targets['object']:
            ts += 1
            if len([p for p in pickupables if 'Sliced' in p['objectId']]) >= 1:
                s += 1

        if np.any([np.any([p['objectId'] in r['receptacleObjectIds']
                           for r in receptacles if r['receptacleObjectIds'] is not None])
                   for p in pickupables]):
            s += 1

        return s, ts

    def reset(self):
        super().reset()


class PickTwoObjAndPlaceTask(BaseTask):
    '''
    pick_two_obj_and_place task
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def goal_satisfied(self, state):
        # check if two objects of 'object' class are in any receptacle of 'parent' class
        pcs = self.goal_conditions_met(state)
        return pcs[0] == pcs[1]

    def goal_conditions_met(self, state):
        ts = 2
        s = 0

        targets = self.get_targets()
        receptacles = get_objects_with_name_and_prop(targets['parent'], 'receptacle', state.metadata)
        pickupables = get_objects_with_name_and_prop(targets['object'], 'pickupable', state.metadata)

        # check if object needs to be sliced
        if 'Sliced' in targets['object']:
            ts += 2
            s += min(len([p for p in pickupables if 'Sliced' in p['objectId']]), 2)

        # placing each object counts as a goal_condition
        s += min(np.max([sum([1 if r['receptacleObjectIds'] is not None
                                   and p['objectId'] in r['receptacleObjectIds'] else 0
                              for p in pickupables])
                         for r in receptacles]), 2)
        return s, ts

    def reset(self):
        super().reset()


class LookAtObjInLightTask(BaseTask):
    '''
    look_at_obj_in_light task
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def goal_satisfied(self, state):
        # check if any object of 'object' class is being held in front of 'toggle' object that is turned on
        pcs = self.goal_conditions_met(state)
        return pcs[0] == pcs[1]

    def goal_conditions_met(self, state):
        ts = 2
        s = 0

        targets = self.get_targets()
        toggleables = get_objects_with_name_and_prop(targets['toggle'], 'toggleable', state.metadata)
        pickupables = get_objects_with_name_and_prop(targets['object'], 'pickupable', state.metadata)
        inventory_objects = state.metadata['inventoryObjects']

        # check if object needs to be sliced
        if 'Sliced' in targets['object']:
            ts += 1
            if len([p for p in pickupables if 'Sliced' in p['objectId']]) >= 1:
                s += 1

        # check if the right object is in hand
        if len(inventory_objects) > 0 and inventory_objects[0]['objectId'] in [p['objectId'] for p in pickupables]:
            s += 1
        # check if the lamp is visible and turned on
        if np.any([t['isToggled'] and t['visible'] for t in toggleables]):
            s += 1

        return s, ts

    def reset(self):
        super().reset()


class PickHeatThenPlaceInRecepTask(BaseTask):
    '''
    pick_heat_then_place_in_recep task
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def goal_satisfied(self, state):
        # check if any object of 'object' class inside receptacle of 'parent' class is hot
        pcs = self.goal_conditions_met(state)
        return pcs[0] == pcs[1]

    def goal_conditions_met(self, state):
        ts = 3
        s = 0

        targets = self.get_targets()
        receptacles = get_objects_with_name_and_prop(targets['parent'], 'receptacle', state.metadata)
        pickupables = get_objects_with_name_and_prop(targets['object'], 'pickupable', state.metadata)

        # check if object needs to be sliced
        if 'Sliced' in targets['object']:
            ts += 1
            if len([p for p in pickupables if 'Sliced' in p['objectId']]) >= 1:
                s += 1

        objs_in_place = [p['objectId'] for p in pickupables for r in receptacles
                         if r['receptacleObjectIds'] is not None and p['objectId'] in r['receptacleObjectIds']]
        objs_heated = [p['objectId'] for p in pickupables if p['objectId'] in self.env.heated_objects]

        # check if object is in the receptacle
        if len(objs_in_place) > 0:
            s += 1
        # check if some object was heated
        if len(objs_heated) > 0:
            s += 1
        # check if the object is both in the receptacle and hot
        if np.any([obj_id in objs_heated for obj_id in objs_in_place]):
            s += 1

        return s, ts

    def reset(self):
        super().reset()


class PickCoolThenPlaceInRecepTask(BaseTask):
    '''
    pick_cool_then_place_in_recep task
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def goal_satisfied(self, state):
        # check if any object of 'object' class inside receptacle of 'parent' class is cold
        pcs = self.goal_conditions_met(state)
        return pcs[0] == pcs[1]

    def goal_conditions_met(self, state):
        ts = 3
        s = 0

        targets = self.get_targets()
        receptacles = get_objects_with_name_and_prop(targets['parent'], 'receptacle', state.metadata)
        pickupables = get_objects_with_name_and_prop(targets['object'], 'pickupable', state.metadata)

        if 'Sliced' in targets['object']:
            ts += 1
            if len([p for p in pickupables if 'Sliced' in p['objectId']]) >= 1:
                s += 1

        objs_in_place = [p['objectId'] for p in pickupables for r in receptacles
                         if r['receptacleObjectIds'] is not None and p['objectId'] in r['receptacleObjectIds']]
        objs_cooled = [p['objectId'] for p in pickupables if p['objectId'] in self.env.cooled_objects]

        # check if object is in the receptacle
        if len(objs_in_place) > 0:
            s += 1
        # check if some object was cooled
        if len(objs_cooled) > 0:
            s += 1
        # check if the object is both in the receptacle and cold
        if np.any([obj_id in objs_cooled for obj_id in objs_in_place]):
            s += 1

        return s, ts

    def reset(self):
        super().reset()


class PickCleanThenPlaceInRecepTask(BaseTask):
    '''
    pick_clean_then_place_in_recep task
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def goal_satisfied(self, state):
        # check if any object of 'object' class inside receptacle of 'parent' class is clean
        pcs = self.goal_conditions_met(state)
        return pcs[0] == pcs[1]

    def goal_conditions_met(self, state):
        ts = 3
        s = 0

        targets = self.get_targets()
        receptacles = get_objects_with_name_and_prop(targets['parent'], 'receptacle', state.metadata)
        pickupables = get_objects_with_name_and_prop(targets['object'], 'pickupable', state.metadata)

        if 'Sliced' in targets['object']:
            ts += 1
            if len([p for p in pickupables if 'Sliced' in p['objectId']]) >= 1:
                s += 1

        objs_in_place = [p['objectId'] for p in pickupables for r in receptacles
                         if r['receptacleObjectIds'] is not None and p['objectId'] in r['receptacleObjectIds']]
        objs_cleaned = [p['objectId'] for p in pickupables if p['objectId'] in self.env.cleaned_objects]

        # check if object is in the receptacle
        if len(objs_in_place) > 0:
            s += 1
        # check if some object was cleaned
        if len(objs_cleaned) > 0:
            s += 1
        # check if the object is both in the receptacle and clean
        if np.any([obj_id in objs_cleaned for obj_id in objs_in_place]):
            s += 1

        return s, ts

    def reset(self):
        super().reset()


class PickAndPlaceWithMovableRecepTask(BaseTask):
    '''
    pick_and_place_with_movable_recep task
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def goal_satisfied(self, state):
        # check if any object of 'object' class is inside any movable receptacle of 'mrecep' class at receptacle of 'parent' class
        pcs = self.goal_conditions_met(state)
        return pcs[0] == pcs[1]

    def goal_conditions_met(self, state):
        ts = 3
        s = 0

        targets = self.get_targets()
        receptacles = get_objects_with_name_and_prop(targets['parent'], 'receptacle', state.metadata)
        pickupables = get_objects_with_name_and_prop(targets['object'], 'pickupable', state.metadata)
        movables = get_objects_with_name_and_prop(targets['mrecep'], 'pickupable', state.metadata)

        # check if object needs to be sliced
        if 'Sliced' in targets['object']:
            ts += 1
            if len([p for p in pickupables if 'Sliced' in p['objectId']]) >= 1:
                s += 1

        pickup_in_place = [p for p in pickupables for m in movables
                           if 'receptacleObjectIds' in p and m['receptacleObjectIds'] is not None
                           and p['objectId'] in m['receptacleObjectIds']]
        movable_in_place = [m for m in movables for r in receptacles
                            if 'receptacleObjectIds' in r and r['receptacleObjectIds'] is not None
                            and m['objectId'] in r['receptacleObjectIds']]
        # check if the object is in the final receptacle
        if len(pickup_in_place) > 0:
            s += 1
        # check if the movable receptacle is in the final receptacle
        if len(movable_in_place) > 0:
            s += 1
        # check if both the object and movable receptacle stack is in the final receptacle
        if np.any([np.any([p['objectId'] in m['receptacleObjectIds'] for p in pickupables]) and
                   np.any([r['objectId'] in m['parentReceptacles'] for r in receptacles]) for m in movables
                   if m['parentReceptacles'] is not None and m['receptacleObjectIds'] is not None]):
            s += 1

        return s, ts

    def reset(self):
        super().reset()


def get_task(task_type, traj, env, args, reward_type='sparse', max_episode_length=2000):
    task_class_str = task_type.replace('_', ' ').title().replace(' ', '') + "Task"

    if task_class_str in globals():
        task = globals()[task_class_str]
        return task(traj, env, args, reward_type=reward_type, max_episode_length=max_episode_length)
    else:
        raise Exception("Invalid task_type %s" % task_class_str)