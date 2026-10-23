<h1 align="center">
ScienceWorld
</h1>

<p align="center">
<!-- Version badge using shields.io -->
  <a href="https://github.com/allenai/ScienceWorld/releases">
    <img src="https://img.shields.io/github/v/release/allenai/ScienceWorld">
  </a>
<!-- Link to tutorials badge using shields.io -->
  <a href="https://huggingface.co/spaces/MarcCote/ScienceWorld">
    <img src="https://img.shields.io/badge/🤗-Demo-yellow">
  </a>
<!-- Follow on twitter badge using shields.io -->
  <a href="https://sciworld.apps.allenai.org">
    <img src="https://img.shields.io/badge/Website-green">
  </a>
</p>

ScienceWorld is a text-based virtual environment centered around accomplishing tasks from the standardized elementary science curriculum.  This code accompanies the paper [ScienceWorld: Is your Textual Agent Smarter than a 5th grader?](https://arxiv.org/abs/2203.07540).

> [!WARNING]
> **Potentially breaking change in 1.3.0:** Environment objects are now enumerated in deterministic UUID order across resets and Scala/JVM versions. This fixes stochastic simulation outcomes, but can change physics trajectories, ambiguous action resolution, gold paths, and observation/JSON ordering compared with 1.2.x. Task generation for a given variation is otherwise unchanged.

<h3 align="center"><img src="https://github.com/allenai/ScienceWorld/blob/main/media/scienceworld_environment.png" width="75%"/></h3>

### Demo and examples

You can try ScienceWorld yourself via our [HuggingFace Space](https://huggingface.co/spaces/MarcCote/ScienceWorld) or read some of the [playthrough transcripts](https://sciworld.apps.allenai.org/explore).

### Citation
```
@inproceedings{wang-etal-2022-scienceworld,
    title = "{S}cience{W}orld: Is your Agent Smarter than a 5th Grader?",
    author = "Wang, Ruoyao  and
      Jansen, Peter  and
      C{\^o}t{\'e}, Marc-Alexandre  and
      Ammanabrolu, Prithviraj",
    editor = "Goldberg, Yoav  and
      Kozareva, Zornitsa  and
      Zhang, Yue",
    booktitle = "Proceedings of the 2022 Conference on Empirical Methods in Natural Language Processing",
    month = dec,
    year = "2022",
    address = "Abu Dhabi, United Arab Emirates",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2022.emnlp-main.775/",
    doi = "10.18653/v1/2022.emnlp-main.775",
    pages = "11279--11298",
}
```

# Quickstart
**Before running:** You will have to have `Java 1.8+` installed on your system (shipped with most linux distributions) and `Python 3.8+`. We recommend creating a conda environment like this:

```bash
conda create --name scienceworld python=3.8
conda activate scienceworld
```

Then, install ScienceWorld either from PyPi:

    pip install scienceworld

or from source in development mode:

    git clone https://github.com/allenai/ScienceWorld.git
    cd ScienceWorld
    pip install .


Run an example random agent, on task 13 (classification: place a non-living thing in a box), for 5 episodes:

    python examples/random_agent.py --task-num=13 --num-episodes=5 --simplifications-preset easy

Run a user console where you can interact with the environment, on task 3 (change of state: melting):

    python examples/human.py --task-num=3 --num-episodes=5


# Web Server Demo

A web server demo is also available, that allows running a ScienceWorld user console that can be interacted with in a web browser.

<h3 align="center"><img src="https://github.com/allenai/ScienceWorld/blob/main/media/web_demo_screenshot.png" width="75%"/></h3>

To run the web server demo:
```bash
conda create --name scienceworld python=3.8
conda activate scienceworld
pip install scienceworld[webserver]
```

Run the web server:

    python examples/scienceworld-web-server-example.py

Point your web browser to:
`localhost:8080`


# ScienceWorld Design
ScienceWorld is written in Scala (2.12.9), and compiles using `sbt` into a JAR file that is run with Java.  For convenience, a Python API is provided (Python >= 3.8), which interfaces using the `py4j` package.

If you modified the Scala code, you can recompile the JAR file by running:
```bash
./simulator/package.sh
pip install -e .
```

# Tasks
The tasks are listed in the table below along with their number of variations. Either the task ID or its name can be used to a task with `env.load()`.

| Task ID | Task Name                                | # Variations |
|-------|----------------------------------------------------|------|
|   1-1 |                                             boil |   30 |
|   1-2 |                                             melt |   30 |
|   1-3 |                                           freeze |   30 |
|   1-4 |                    change-the-state-of-matter-of |   30 |
|   2-1 |                                  use-thermometer |  540 |
|   2-2 |            measure-melting-point-known-substance |  436 |
|   2-3 |          measure-melting-point-unknown-substance |  300 |
|   3-1 |                                  power-component |   20 |
|   3-2 | power-component-renewable-vs-nonrenewable-energy |   20 |
|   3-3 |                                test-conductivity |  900 |
|   3-4 |          test-conductivity-of-unknown-substances |  600 |
|   4-1 |                                find-living-thing |  300 |
|   4-2 |                            find-non-living-thing |  300 |
|   4-3 |                                       find-plant |  300 |
|   4-4 |                                      find-animal |  300 |
|   5-1 |                                       grow-plant |  126 |
|   5-2 |                                       grow-fruit |  126 |
|   6-1 |                                    chemistry-mix |   32 |
|   6-2 |              chemistry-mix-paint-secondary-color |   36 |
|   6-3 |               chemistry-mix-paint-tertiary-color |   36 |
|   7-1 |                           lifespan-longest-lived |  125 |
|   7-2 |                          lifespan-shortest-lived |  125 |
|   7-3 |       lifespan-longest-lived-then-shortest-lived |  125 |
|   8-1 |                           identify-life-stages-1 |   14 |
|   8-2 |                           identify-life-stages-2 |   10 |
|   9-1 |                   inclined-plane-determine-angle |  168 |
|   9-2 |           inclined-plane-friction-named-surfaces | 1386 |
|   9-3 |         inclined-plane-friction-unnamed-surfaces |  162 |
|  10-1 |                   mendelian-genetics-known-plant |  120 |
|  10-2 |                 mendelian-genetics-unknown-plant |  480 |

## Simplifications
ScienceWorld supports a number of simplifications that can be applied to the environment to make it easier for agents to learn. These simplifications can be applied by passing the `--simplifications-preset` argument to the command line interface, or by passing the `simplifications` argument to the Python API.

The available simplifications are:
- `teleportAction`: Allows agents to instantly move to any location in the environment.
- `openDoors`: All doors in the environment are open by default.
- `selfWateringFlowerPots`: Automatically waters all flower pots in the environment.
- `noElectricalAction`: Disables electrical actions, making it easier for agents to learn tasks that do not require electrical actions.
- `openContainers`: All containers in the environment are open by default.

The `--simplifications-preset` argument can be set to `easy` to apply the following simplifications:
- `teleportAction`
- `openDoors`
- `selfWateringFlowerPots`
- `noElectricalAction` (for non-connectivity tasks)

> [!WARNING]
> The `easy` preset differs from what is described in the paper (see Appendix B.5). The `openContainers` is not included in that preset and should manually be added if desired.


# Baseline Agents
**DRRN:** https://github.com/cognitiveailab/drrn-scienceworld

**KG-A2C:** https://github.com/cognitiveailab/kga2c-scienceworld

**CALM:** https://github.com/cognitiveailab/calm-scienceworld

**Behavior Cloning and Decision Transformer:** https://github.com/cognitiveailab/t5-scienceworld



# Developers

To compile the ScienceWorld JAR file, follow these steps:

### Prerequisites
You will need to have `Java 1.8+` SDK installed on your system (shipped with most linux distributions). E.g. on Ubuntu, you can install it with:

    sudo apt-get install openjdk-21-jdk

Then, install sbt (Scala Build Tool) by running:
```bash
    echo "deb https://repo.scala-sbt.org/scalasbt/debian all main" | sudo tee /etc/apt/sources.list.d/sbt.list
    echo "deb https://repo.scala-sbt.org/scalasbt/debian /" | sudo tee /etc/apt/sources.list.d/sbt_old.list
    curl -sL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x2EE0EA64E40A89B84B2DF73499E82A75642AC823" | sudo tee /etc/apt/trusted.gpg.d/sbt.asc
    sudo apt-get update
    sudo apt-get install sbt
```

### Building the JAR
Once you have `sbt` installed, you can compile the ScienceWorld JAR file by running:
```bash
./simulator/package.sh
```
