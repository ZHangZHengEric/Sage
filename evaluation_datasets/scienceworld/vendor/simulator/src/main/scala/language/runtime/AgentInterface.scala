package language.runtime

import java.io.PrintWriter

import language.model.{ActionRequestDef, ClassDef, PredicateDef, Program, RuleDef}
import language.parser.Parser
import language.runtime.Reader.parseProgramFromFile
import language.runtime.inputparser.InputParser
import language.runtime.runners.{ActionRunner, ObjectPropertyRunner, PredicateRunner, RuleRunner}
import language.struct.{DynamicValue, EnvObject}

import scala.io.StdIn.readLine

class AgentInterface(val scriptFilename:String) {

  // Step 1: Parse script
  val parser = new Parser()
  val (program, success, importedFiles) = parseProgramFromFile(parser, scriptFilename)
  if (!success) {
    println ("Parse unsuccessful. ")
    sys.exit(1)
  }

  // Step 2: Create action space handler
  val possibleActions = program.actions.getOrElse(List.empty[ActionRequestDef]).toArray
  val actionRunner = new ActionRunner(possibleActions, program.taxonomy)

  // Step 3: Run interpreter / initialization
  println("Interpreter:")
  val interpreter = new Interpreter(program.definesLUT, program.classLUT, actionRunner)
  val result = interpreter.walkOneStep(program.statements.get)

  if (result.success == true) {
    println("Interpreter completed successfully. ")
  } else {
    println("Interpreter exited with error. ")
    sys.exit(1)
  }

  // Step 4: Create class definition LUT, and a faux interpreter for handling evaluating class property functions
  val classDefLUT = ObjectPropertyRunner.mkClassDefLUT(program.classes)
  val fauxInterpreter = new Interpreter(program.definesLUT, program.classLUT, new ActionRunner(possibleActions, program.taxonomy))    // Faux interpreter for running object property functions, that's reset every time it's run.

  // Step 5: Get main agent
  if (interpreter.getMainAgent().isEmpty) {
    println ("ERROR: Agent is not defined.  Did you forget to include a call to setAgent()?")
    sys.exit(1)
  }
  private val agent = interpreter.getMainAgent().get

  // Step 6: Create user input parser
  val userInputParser = new InputParser(program.actions.getOrElse( List.empty[ActionRequestDef] ), actionRunner)

  /*
   * Accessors
   */
  def getAgent():EnvObject = this.agent


  /*
   * Objects visible to the agent
   */

  // TODO: Currently just returns the current room, rather than a list of all visible objects
  def getAgentVisibleObjects():(Boolean, EnvObject)  = {
    val agentContainer = agent.getContainer()
    if (agentContainer.isEmpty) {
      val errStr = "ERROR: Agent is not in container."
      return (false, new EnvObject)
    }

    return (true, agentContainer.get)
  }

  /*
   * User Input
   */
  def getUserInput():String = {
    print("> ")
    val inputStr = readLine()
    return inputStr
  }

  def processUserInput(inputStr:String):(Boolean, String) = {   // (Success, statusString)

    val (successVisible, visibleObjects) = this.getAgentVisibleObjects()      // TODO: Currently just a reference to the container (current room), rather than a list
    if (!successVisible) throw new RuntimeException("ERROR: Agent is not in container.")

    //val (successUserInput, errStr, userStr) = userInputParser.parse(inputStr, interpreter.objectTreeRoot, agent)
    val (successUserInput, errStr, userStr) = userInputParser.parse(inputStr, visibleObjects, agent)
    if (!successUserInput) {
      println("ERROR: " + errStr)
    } else {
      println(userStr)
    }

    return (successUserInput, userStr)
  }

  /*
   * Step
   */

  def step(userInputString:String, debugOutput:Boolean = false):(Boolean, String, String) = {      // Success, errorString, Output String
    val outputStr = new StringBuilder
    val (successInput, userString) = this.processUserInput(userInputString)
    if (!successInput) {
      outputStr.append("Error processing input.\n")
      outputStr.append(userString + "\n")
    }

    // Run/automatically populate any object property functions
    ObjectPropertyRunner.populateRunnableProperties(interpreter.objectTreeRoot, classDefLUT, program.taxonomy, fauxInterpreter)

    // ActionRunner tick: Take any queued actions and put them on the current requests.
    actionRunner.tick()

    // Step 6: Run predicates individually
    val predicates = program.predicates.getOrElse(List.empty[PredicateDef]).toArray
    val pr = new PredicateRunner(predicates, interpreter.objectTreeRoot, program.definesLUT, program.classLUT, program.taxonomy, actionRunner, interpreter, debugOutput)

    // Step 7: Run rules
    val rules = program.rules.getOrElse(List.empty[RuleDef]).toArray
    val rr = new RuleRunner(rules, pr, debugOutput)

    if (debugOutput) {
      // Step 4: Display variables (debug)
      println("VariableLUT:")
      println(interpreter.scopedVariableLUT.toString())

      // Step 5: Display object tree (debug)
      println("")
      println("Object Tree:")
      println(interpreter.objectTreeRoot.toString())

      println("")
      println("Action Requests:")
      println(actionRunner.toString())

      println("")
      println("ChangeLog:")
      println(rr.toStringChangeLog())

      val pw = new PrintWriter("out.html")
      pw.println("<html><head>")
      pw.println("<style>\ntable, th, td {\n  border: 1px solid black;\n  border-collapse: collapse; padding:5px; text-align:left\n}\ntable { min-width: 500px; }</style>")
      pw.println("</head><body>")
      pw.println(rr.toHTMLChangeLog())
      pw.println("</body></html>")
      pw.close()
    }

    // Get the room/container that the agent is in
    val agentContainer = agent.getContainer()
    if (agentContainer.isEmpty) {
      val errStr = "ERROR: Agent is not in container."
      return (false, errStr, errStr)
    }

    // Get a description of the container (nominally, a room).
    /*
    val description = agentContainer.get.getProperty("description")
    if (description.isEmpty) {
      val errStr = "ERROR: No description available for agent's current container:\n" + agentContainer.get.toString()
      return (false, errStr, errStr)
    }

    if (!description.get.isString()) {
      val errStr = "ERROR: Object description is not a string (expected: " + DynamicValue.TYPE_STRING + ", found: " + description.get.getTypeStr() + ")."
      return (false, errStr, errStr)
    }

    val descriptionText = description.get.getString().get
     */
    // Get console output from interpreter
    val descriptionText = interpreter.getConsoleOutput().mkString("\n")
    interpreter.consoleOutputClear()
    outputStr.append(descriptionText)

    // Return
    return (true, "", outputStr.toString())
  }


  /*
   * String methods
   */
  def printDebugDisplay(): Unit = {
    // Step 4: Display variables (debug)
    println("VariableLUT:")
    println(interpreter.scopedVariableLUT.toString())

    // Step 5: Display object tree (debug)
    println("")
    println("Object Tree:")
    println(interpreter.objectTreeRoot.toStringIncludingContents())

    println("")
    println("Action Requests:")
    println(actionRunner.toString())
  }

}
