package scienceworld.tasks

import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.GoalSequence
import scienceworld.tasks.goals.specificgoals.{GoalChangeStateOfMatter, GoalFind, GoalIsDifferentStateOfMatter, GoalIsNotStateOfMatter, GoalIsStateOfMatter}

class Task(val taskName:String, val description:String, val goalSequence:GoalSequence, val taskObjects:Array[EnvObject] = Array.empty[EnvObject], val taskModifiers:Array[TaskModifier]) {

}



object Task {

  def mkUnaccomplishableTask(): Task = {
    val goalSequence = new GoalSequence( Array(new GoalFind("random_object_name")) )
    return new Task("unknown", "unknown", goalSequence, taskModifiers = Array.empty[TaskModifier])
  }

}
