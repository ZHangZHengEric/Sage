package scienceworld.input

import main.scala.scienceworld.actions.ActionTeleport
import scienceworld.actions.{Action, ActionActivate, ActionCloseDoor, ActionConnectElectrical, ActionDeactivate, ActionDisconnectElectrical, ActionDunkObject, ActionEat, ActionFlush, ActionFocus, ActionInventory, ActionLookAround, ActionLookAt, ActionLookIn, ActionMix, ActionMoveObject, ActionMoveThroughDoor, ActionOpenDoor, ActionPickUpObjectIntoInventory, ActionPourObject, ActionPutDownObjectIntoInventory, ActionRead, ActionResetTask, ActionTaskDesc, ActionUseDevice, ActionWait1, ActionWait10}
import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{GoalSequence, ObjMonitor}

object ActionTypecaster {

  def typecastAction(actionIn:InputMatch, objMonitor:ObjMonitor, goalSequence:GoalSequence, agent:Agent):Action = {
    val action = actionIn.actionRequestDef.get
    val assignments = actionIn.varLUT.toMap

    action.name match {
      case ActionFocus.ACTION_NAME => new ActionFocus(action, assignments, objMonitor)
      case ActionResetTask.ACTION_NAME => new ActionResetTask(action, assignments, objMonitor, goalSequence)

      case ActionOpenDoor.ACTION_NAME => new ActionOpenDoor(action, assignments)
      case ActionCloseDoor.ACTION_NAME => new ActionCloseDoor(action, assignments)
      case ActionMoveThroughDoor.ACTION_NAME => new ActionMoveThroughDoor(action, assignments)
      case ActionLookAround.ACTION_NAME => new ActionLookAround(action, assignments)
      case ActionLookAt.ACTION_NAME => new ActionLookAt(action, assignments)
      case ActionLookIn.ACTION_NAME => new ActionLookIn(action, assignments)
      case ActionActivate.ACTION_NAME => new ActionActivate(action, assignments)
      case ActionDeactivate.ACTION_NAME => new ActionDeactivate(action, assignments)
      case ActionEat.ACTION_NAME => new ActionEat(action, assignments)
      case ActionMoveObject.ACTION_NAME => new ActionMoveObject(action, assignments)
      case ActionPourObject.ACTION_NAME => new ActionPourObject(action, assignments)
      case ActionUseDevice.ACTION_NAME => new ActionUseDevice(action, assignments)
      case ActionRead.ACTION_NAME => new ActionRead(action, assignments)
      case ActionFlush.ACTION_NAME => new ActionFlush(action, assignments)
      case ActionConnectElectrical.ACTION_NAME => new ActionConnectElectrical(action, assignments)
      case ActionDisconnectElectrical.ACTION_NAME => new ActionDisconnectElectrical(action, assignments)
      case ActionWait1.ACTION_NAME => new ActionWait1(action, assignments)
      case ActionWait10.ACTION_NAME => new ActionWait10(action, assignments)
      case ActionInventory.ACTION_NAME => new ActionInventory(action, assignments)
      case ActionMix.ACTION_NAME => new ActionMix(action, assignments)
      case ActionTaskDesc.ACTION_NAME => new ActionTaskDesc(action, assignments)
      case ActionTeleport.ACTION_NAME => new ActionTeleport(action, assignments)
      case ActionDunkObject.ACTION_NAME => new ActionDunkObject(action, assignments)

      // Remapped actions
        // "Pick up" uses move, but substitutes in the agent's inventory as the 'moveTo' destination
      case ActionPickUpObjectIntoInventory.ACTION_NAME => new ActionMoveObject(action, ActionPickUpObjectIntoInventory.remap(assignments, agent))
      // "Put down" uses move, but substitutes in the agent's current location (container) as the 'moveTo' destination
      case ActionPutDownObjectIntoInventory.ACTION_NAME => new ActionMoveObject(action, ActionPutDownObjectIntoInventory.remap(assignments, agent))

      case _ => throw new RuntimeException("ERROR: Unknown action name: " + action.name)
    }

  }

}
