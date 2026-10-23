# exampleLoadGoldPaths.py
#
# This example illustrates how to traverse the gold (oracle) paths for ScienceWorld.
#

import json

filenameIn = "goldsequences-0-1-2-3.json"
f = open(filenameIn)
data = json.load(f)

print(type(data))
print("Tasks stored in this gold data: " + str(data.keys()))
numMoves = 0
numSequences = 0

linesOut = []

for taskIdx in data.keys():
    print("Task Index: " + str(taskIdx))

    taskData = data[taskIdx]
    taskName = taskData['taskName']

    goldSequences = taskData['goldActionSequences']

    for goldSequence in goldSequences:
        variationIdx = goldSequence['variationIdx']
        taskDescription = goldSequence['taskDescription']
        fold = goldSequence['fold']
        path = goldSequence['path']

        print("\n\n-----------------------------------------------------------\n")

        print("TaskDescription: " + str(taskDescription))

        lineOut = str(taskIdx) + "\t" + str(variationIdx) + "\t" + str(fold) + "\t" + str(taskDescription)
        linesOut.append(lineOut)

        for step in path:
            action = step['action']
            obs = step['observation']
            score = step['score']
            isCompleted = step['isCompleted']
            print("> " + str(action))
            print(obs)
            print("")

            numMoves += 1
        numSequences += 1


print("----------------------")
print("Summary Statistics:")
print("numTasks: " + str(len(data.keys())))
print("numSequences: " + str(numSequences))
print("numMoves: " + str(numMoves))
