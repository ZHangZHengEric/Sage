# Dataset

The ALFWorld dataset contains 3,553 training games, 140 seen and 134 unseen validation games.

## Download

Download PDDL, Game Files and pre-trained MaskRCNN model:

```bash
python scripts/alfworld-download
```

Additional Seq2Seq data and pre-trained BUTLER checkpoints (All Tasks):

```bash
python scripts/alfworld-download --extra
```

## File Structure

```
$ALFWORLD_DATA/json_2.1.1/train/task_type-object-movableReceptacle-receptacle-sceneNum/trial_ID/                   (trajectory root)
$ALFWORLD_DATA/json_2.1.1/train/task_type-object-movableReceptacle-receptacle-sceneNum/trial_ID/traj_data.json     (trajectory metadata)
$ALFWORLD_DATA/json_2.1.1/train/task_type-object-movableReceptacle-receptacle-sceneNum/trial_ID/initial_state.pddl (PDDL description of the initial state)
$ALFWORLD_DATA/json_2.1.1/train/task_type-object-movableReceptacle-receptacle-sceneNum/trial_ID/game.tw-pddl       (textworld game file)
```

## JSON Structure

Dictionary structure of `traj_data.json`:

Task Info:
```
['task_id'] = "trial_00003_T20190312_234237"        (unique trajectory ID)
['task_type'] = "pick_heat_then_place_in_recep"     (one of 7 task types)
['pddl_params'] = {'object_target': "AlarmClock",   (object)
                   'parent_target': "DeskLamp",     (receptacle)
                   'mrecep_target': "",             (movable receptacle)
                   "toggle_target": "",             (toggle object)
                   "object_sliced": false}          (should the object be sliced?)
```

Scene Info:
```
['scene'] =  {'floor_plan': "FloorPlan7",           (THOR scene name)
              'scene_num' : 7,                      (THOR scene number)
              'random_seed': 3810970210,            (seed for initializing object placements)
              'init_action' : <API_CMD>,            (called to set the starting position of the agent)
              'object_poses': <LIST_OBJS>,          (initial 6DOF poses of objects in the scene)
              'object_toggles': <LIST_OBJS>}        (initial states of togglable objects)
```

Language Annotations:
```
['turk_annotations']['anns'] =
             [{'task_desc': "Examine a clock using the light of a lamp.",                 (goal instruction)
               'high_descs': ["Turn to the left and move forward to the window ledge.",   (list of step-by-step instructions)
                              "Pick up the alarm clock on the table", ...],               (indexes aligned with high_idx)
               'votes': [1, 1, 1]                                                         (AMTurk languauge quality votes)
              },
              ...]
```

Expert Demonstration:
```
['plan'] = {'high_pddl':
                ...,
                ["high_idx": 4,                          (high-level subgoal index)
                 "discrete_action":
                     {"action": "PutObject",             (discrete high-level action)
                      "args": ["bread", "microwave"],    (discrete params)
                 "planner_action": <PDDL_ACTION> ],      (PDDL action)
                ...],

            'low_actions':
                ...,
                ["high_idx": 1,                          (high-level subgoal index)
                 "discrete_action":
                     {"action": "PickupObject",          (discrete low-level action)
                      "args":
                          {"bbox": [180, 346, 332, 421]} (bounding box for interact action)
                           "mask": [0, 0, ... 1, 1]},    (compressed pixel mask for interact action)
                 "api_action": <API_CMD> ],              (THOR API command for replay)
                ...],
           }
```

Images:
```
['images'] = [{"low_idx": 0,                    (low-level action index)
               "high_idx": 0,                   (high-level action index)
               "image_name": "000000000.jpg"}   (image filename)
             ...]
```

## Data & Generation

#### PDDL states from ALFRED

To generate `initial_state.pddl` from ALFRED `traj_data.json` files:

```bash
python scripts/augment_pddl_states.py --data_path $ALFWORLD_DATA/json_2.1.1/train
```

#### Adding additional attributes to TextWorld games

1. Use [augment_pddl_states.py](../../scripts/augment_pddl_states.py#L254) to dump additional attributes and properties from THOR into `initial_state.pddl`.
2. Use [alfworld-generate](../../scripts/alfworld-generate) to generate `game.tw-pddl` files from the new `initial_state.pddl`s. This will use the expert to check if the text game is solvable and then dump a game file used by the text-engine.
3. Modify the demangler in [`misc.py`](../../alfworld/agents/utils/misc.py#L64) to display the attribute in Textworld, or modify the grammar in [`alfred.twl2`](https://github.com/alfworld/alfworld/blob/master/data/textworld_data/logic/alfred.twl2) to your needs.

#### Generating TextWorld games that use human goal annotations.

```bash
alfworld-generate --data_path $ALFWORLD_DATA/json_2.1.1 --save_path custom_dataset/ --goal_desc_human_anns_prob 1
```

## Mask-RCNN Detector

#### Generating MaskRCNN training images from ALFRED

To generate image and instance-segmentation pairs from ALFRED training scenes:

```bash
python scripts/augment_trajectories.py --data_path $ALFWORLD_DATA/json_2.1.1/train --save_path $ALFWORLD_DATA/raw_images --num_threads 4
```

#### Fine-tuning MaskRCNN

To fine-tune a COCO-trained MaskRCNN model:

```bash
python scripts/train_mrcnn.py --data_path $ALFWORLD_DATA/raw_images --save_path $ALFWORLD_DATA/mrcnn --balance_scenes --object_types objects  --batch_size 32
```

#### Pre-trained Models
The default pre-trained model provided in the repo is trained on 73 object classes without receptacles. We also provide [other models](https://github.com/alfworld/alfworld/releases/tag/0.2.2) for receptacles (32 receptacle classes) and all objects (105 classes). These pre-trained models are named `mrcnn_*`.
