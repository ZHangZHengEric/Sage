package language.parser

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionRequestDef, ActionTrigger, AddObjToWorld, ArrayAppend, ArrayDef, ArrayElem, ArrayRemove, Assignment, AssignmentArrayElem, AssignmentObjProp, Bool, BuiltInFunction, ClassDef, Condition, ConditionElem, ConditionExpr, ConditionLR, ConditionOperator, ConstructorDef, Define, DeleteObject, Exit, Expr, ForLoop, ForLoopArrayElem, ForRange, Identifier, IfStatement, IfStatementCondition, ImportFile, ImportTaxonomy, MoveObject, NegatedExpr, Number, ObjectCreate, ObjectProperty, Operator, Param, ParamList, ParamSig, ParamSigList, PredicateDef, PredicateRef, Print, PrintLog, Program, PropertyDefault, PropertyFunction, RequestAction, Return, RuleDef, SetAgent, Statement, Str}

import scala.util.parsing.combinator.syntactical.StandardTokenParsers


class Parser extends StandardTokenParsers {


  lexical.reserved += ("var", "def", "pred", "get", "set", "rule", "println", "printlnLog", "predicates", "rules", "init", "import", "new", "return", "true", "false", "addObjToWorld", "deleteObject", "moveObj", "to", "if", "else", "in", "defines", "defineprop", "actions", "action", "requestAction", "classes", "class", "extends", "prop", "override", "for", "until", "exit", "setAgent", "constructor", "trigger", "Array", "append", "remove")

  lexical.delimiters += ("-o", "*", "/", "%", "+", "-", "(", ")", "{", "}", "=", "<", ">", "==", "!=", "<=", ">=", ",", "::", ":", "[", "]", "\"", "'", ".", "&&", "||", "!", "->", "~", "@", "#", "<-")


  /*
   * Program
   */

  def program: Parser[Program] = opt(importFileList) ~ opt(definesList) ~ opt(classList) ~ opt(predicateList) ~ opt(actionList) ~ opt(ruleList) ~ opt("@" ~ "init" ~> codeblock) ^^ {
    case importlist ~ defines ~ classes ~ preds ~ actions ~ rules ~ code => new Program(importlist, defines, classes, preds, actions, rules, code)
  }

  def definesList:Parser[List[Define]] = "@" ~ "defines" ~> rep(positioned(define)) ^^ {
    case defines => defines
  }

  def define:Parser[Define] = "#" ~ "defineprop" ~> ident ~ ident ^^ {
    case name ~ replacewith => new Define(name, replacewith)
  }

  def classList:Parser[List[ClassDef]] = "@" ~ "classes" ~> rep(positioned(classDef)) ^^ {
    case classes => classes
  }

  def predicateList: Parser[List[PredicateDef]] = "@" ~ "predicates" ~> rep(positioned(predicateDef)) ^^ {
    case preds => preds
  }

  def actionList: Parser[List[ActionRequestDef]] = "@" ~ "actions" ~> rep(positioned(actionReqDef)) ^^ {
    case actions => actions
  }

  def ruleList: Parser[List[RuleDef]] = "@" ~ "rules" ~> rep(positioned(ruleDef)) ^^ {
    case rules => rules
  }



  // Codeblock
  def codeblock: Parser[List[Statement]] = rep(statement) ^^ {
    a => a
  }

  def statement: Parser[Statement] = positioned(println | printlnLog | predicateDef | ruleDef | assignmentFirst | assignment | assignmentObjProp | assignmentArrayElem | returnStatement | addObjToWorld | moveObj | deleteObject | runAction | ifStatement | forLoop | forLoopContained | exit | setAgent | arrayAppend | arrayRemove)

  def returnStatement: Parser[Return] = "return" ~> expr ^^ {
    case e => new Return(e)
  }

  /*
   * Classes
   */

  def classDef:Parser[ClassDef] = "class" ~ ident ~ "extends" ~ ident ~ "{" ~ classConstructorDef ~ rep(positioned(propertyDefaultDef)) ~ rep(positioned(propertyFunctionDef)) ~ "}" ^^ {
    case _ ~ classname ~ _ ~ superclass ~ _ ~ constructor ~ propertydefaults ~ propertyfunctions ~ _ => new ClassDef(classname, superclass, constructor, propertydefaults, propertyfunctions)
  }

  def classConstructorDef:Parser[ConstructorDef] = ("constructor" ~> paramSigList) ~ ("{" ~> opt(rep(statement)) <~ "}") ^^ {
    case paramsiglist ~ statements => new ConstructorDef(paramsiglist, statements)
  }

  def propertyDefaultDef:Parser[PropertyDefault] = ("prop" ~> ident) ~ ("=" ~> expr) ^^ {
    case propname ~ valueexpr => new PropertyDefault(propname, valueexpr)
  }

  def propertyFunctionDef:Parser[PropertyFunction] = opt("*") ~ opt("override") ~ "prop" ~ ident ~ "=" ~ "{" ~ rep(statement) <~ "}" ^^ {
    case None ~ None ~ _ ~ propname ~ _ ~ _ ~ statements => new PropertyFunction(propname, isOverride = false, calculateAtRuntime = false, statements)
    case None ~ over ~ _ ~ propName ~ _ ~ _ ~ statements => new PropertyFunction(propName, isOverride = true, calculateAtRuntime = false, statements)
    case calc ~ None ~ _ ~ propname ~ _ ~ _ ~ statements => new PropertyFunction(propname, isOverride = false, calculateAtRuntime = true, statements)
    case calc ~ over ~ _ ~ propName ~ _ ~ _ ~ statements => new PropertyFunction(propName, isOverride = true, calculateAtRuntime = true, statements)
  }

  /*
   * Predicates
   */
  def predicateDef: Parser[PredicateDef] = "pred" ~> ident ~ paramSigList ~ "=" ~ "{" ~ opt(rep(statement)) ~ opt(predicateGetter) ~ opt(predicateSetter) ~ "}" ^^ {
    case name ~ paramlist ~ _ ~ _ ~ statements ~ getter ~ setter ~ _ => new PredicateDef(name, paramlist, statements, getter, setter)                        // Clunky?
  }

  def paramSigList: Parser[ParamSigList] = "(" ~> rep(paramSig <~ opt(",")) <~ ")" ^^ {
    case params => new ParamSigList(params)
  }

  def paramSig: Parser[ParamSig] = ident ~ ":" ~ ident ^^ {
    case name ~ _ ~ objtype => new ParamSig(name, objtype)
  }

  def predicateGetter: Parser[List[Statement]] = "get" ~ "{" ~> rep(statement) <~ "}" ^^ {
    case statements => statements
  }

  def predicateSetter: Parser[List[Statement]] = "set" ~ "{" ~> rep(statement) <~ "}" ^^ {
    case statements => statements
  }

  /*
   * Action Requests
   */
  def actionReqDef: Parser[ActionRequestDef] = "action" ~> ident ~ paramSigList ~ ("{" ~> rep(actionTrigger) <~ "}") ^^ {
    case name ~ paramlist ~ triggers => new ActionRequestDef(name, paramlist, triggers, uniqueActionID = -1)
  }

  def actionTrigger:Parser[ActionTrigger] = ("trigger" ~ ":" ~> actionExprTerm) ~ rep("+" ~> actionExprTerm) ^^ {
    case elem ~ elems => new ActionTrigger( List(elem) ++ elems)
  }

  def actionExprTerm:Parser[ActionExpr] = actionExprIdent | actionExprOR ^^ {
    case x => x
  }

  def actionExprOR:Parser[ActionExprOR] = stringLit ^^ {
    case str => new ActionExprOR( str.split("\\|").toList )
  }

  def actionExprIdent:Parser[ActionExprIdentifier] = ident ^^ {
    case name => new ActionExprIdentifier(name)
  }

  /*
   * Rules
   */
  def ruleDef: Parser[RuleDef] = "rule" ~> ident ~ paramSigList ~ "::" ~ rep(predicateRef <~ opt("*")) ~ "-o" ~ rep(predicateRef <~ opt("*")) ^^ {
    case rulename ~ paramsiglist ~ _ ~ preconditions ~ _ ~ postconditions => new RuleDef(rulename, paramsiglist, preconditions, postconditions)
  }

  def predicateRef: Parser[PredicateRef] = ident ~ positioned(paramList) ^^ {
    case name ~ paramList => new PredicateRef(name, paramList)
  }

  def paramList: Parser[ParamList] = "(" ~> rep(param <~ opt(",")) <~ ")" ^^ {
    case params => new ParamList(params)
  }

  def param: Parser[Param] = ident ~ "=" ~ ident ^^ {
    case name ~ _ ~ value => new Param(name, value)
  }
  //def ruleDef:Parser[RuleDef] = positioned(ident) ~ "(" ~ ")" ~ "="

  /*
   * Import statements
   */
  def importFile:Parser[ImportFile] = "import" ~> stringLit ^^ {
    case filename => new ImportFile(filename)
  }

  def importFileList:Parser[List[ImportFile]] = rep(importFile) ^^ {
    case importList => importList
  }

  /*
   * Statements (printing)
   */
  //def println:Parser[Print] = "println" ~ "(" ~> expr <~ ")" ^^ {
  def println:Parser[Print] = "println" ~ "(" ~> expr <~ ")" ^^ {
    case e => new Print(e)
  }

  def printlnLog:Parser[PrintLog] = "printlnLog" ~ "(" ~> expr <~ ")" ^^ {
    case e => new PrintLog(e)
  }

  def exit:Parser[Exit] = "exit" ~ "(" ~> numericLit <~ ")" ^^ {
    case num => new Exit(num.toInt)
  }

  /*
   * Statements (other)
   */
  def addObjToWorld:Parser[AddObjToWorld] = "addObjToWorld" ~ "(" ~> expr <~ ")" ^^ {
    case e => new AddObjToWorld(e)
  }

  def moveObj:Parser[MoveObject] = "moveObj" ~ "(" ~> expr ~ "to" ~ expr <~ ")" ^^ {
    case objtomove ~ _ ~ moveto => new MoveObject(objtomove, moveto)
  }

  def deleteObject:Parser[DeleteObject] = "deleteObject" ~ "(" ~> expr <~ ")" ^^ {
    case e => new DeleteObject(e)
  }

  def setAgent:Parser[SetAgent] = "setAgent" ~ "(" ~> expr <~ ")" ^^ {
    case e => new SetAgent(e)
  }

  /*
   * Statement (running actions)
   */
  def runAction:Parser[RequestAction] = "requestAction" ~> positioned(predicateRef) ^^ {
    case predref => new RequestAction(predref)
  }

  /*
   * Statements (assignment)
   */
  def assignmentFirst:Parser[Assignment] = "var" ~> ident ~ "=" ~ expr ^^ {
    case varname ~ _ ~ expr => new Assignment(varname, expr, firstDefinition = true)
  }

  def assignment:Parser[Assignment] = ident ~ "=" ~ expr ^^ {
    case varname ~ _ ~ expr => new Assignment(varname, expr, firstDefinition = false)
  }

  def assignmentObjProp:Parser[AssignmentObjProp] = objectProperty ~ "=" ~ expr ^^ {
    case objprop ~ _ ~ expr => new AssignmentObjProp(objprop, expr)
  }

  def assignmentArrayElem:Parser[AssignmentArrayElem] = arrayElem ~ "=" ~ expr ^^ {
    case arrayElem ~ _ ~ expr => new AssignmentArrayElem(arrayElem, expr)
  }

  /*
   * Statements (array appending/removing)
   */
  def arrayAppend:Parser[ArrayAppend] = expr ~ ("." ~ "append" ~ "(" ~> expr <~ ")") ^^ {
    case varexpr ~ valueexpr => new ArrayAppend(varexpr, valueexpr)
  }

  def arrayRemove:Parser[ArrayRemove] = expr ~ ("." ~ "remove" ~ "(" ~> expr <~ ")") ^^ {
    case varexpr ~ valueexpr => new ArrayRemove(varexpr, valueexpr)
  }

  /*
   * Loops (for loops)
   */

  // Conventional for loop (e.g. for (i <- 0 until 10 by 2) )
  def forLoop:Parser[ForLoop] = ("for" ~ "(" ~> ident) ~ ("<-" ~> forRange <~ ")") ~ ("{" ~> codeblock <~ "}") ^^ {
    case varname ~ range ~ code => new ForLoop(varname, range, code)
  }

  def forRange:Parser[ForRange] = expr ~ "until" ~ expr ~ opt("by" ~> expr) ^^ {
    case start ~ _ ~ until ~ None => new ForRange(start, until, None)
    case start ~ _ ~ until ~ by => new ForRange(start, until, by)
  }

  // For loop for contained objects
  def forLoopContained:Parser[ForLoopArrayElem] = ("for" ~ "(" ~> ident) ~ ("<-" ~> expr <~ ")") ~ ("{" ~> codeblock <~ "}") ^^ {
    case varname ~ expr ~ code => new ForLoopArrayElem(varname, expr, code)
  }

  /*
   * Conditionals (if statements)
   */

  def ifStatement:Parser[IfStatement] = conditional ~ codeblock ~ opt(rep(conditionalElseIf)) ~ opt(conditionalElse) <~ "}" ^^ {
    case ifcond ~ ifcode ~ None ~ None => {
      new IfStatement(List(new IfStatementCondition(IfStatementCondition.MODE_IF, Some(ifcond), ifcode)))
    }
    case ifcond ~ ifcode ~ None ~ elseblock => {
      new IfStatement(List(new IfStatementCondition(IfStatementCondition.MODE_IF, Some(ifcond), ifcode)) ++ List(elseblock.get))
    }
    case ifcond ~ ifcode ~ elseiflist ~ None => {
      new IfStatement(List(new IfStatementCondition(IfStatementCondition.MODE_IF, Some(ifcond), ifcode)) ++ elseiflist.get )
    }
    case ifcond ~ ifcode ~ elseiflist ~ elseblock => {
      new IfStatement(List(new IfStatementCondition(IfStatementCondition.MODE_IF, Some(ifcond), ifcode)) ++ elseiflist.get ++ List(elseblock.get))
    }
  }

  def conditional:Parser[ConditionExpr] = "if" ~ "(" ~> conditionExpr <~ ")" ~ "{" ^^ {
    case condition => condition
  }

  def conditionalElseIf:Parser[IfStatementCondition] = "}" ~ "else" ~> conditional ~ codeblock ^^ {
    case cond ~ code => new IfStatementCondition(IfStatementCondition.MODE_ELSEIF, Some(cond), code)
  }

  def conditionalElse:Parser[IfStatementCondition] = "}" ~ "else" ~ "{" ~> codeblock ^^ {
    case code => new IfStatementCondition(IfStatementCondition.MODE_ELSE, None, code)
  }


  /*
   * Conditionals (conditional expressions)
   */
  def conditionExpr:Parser[ConditionExpr] = conditionFactor ~ rep(("&&" | "||") ~ conditionFactor) ^^ {
    case a ~ List() => a
    case a ~ b => {
      def appendExpression(c:ConditionOperator, p:ConditionOperator):ConditionOperator = {
        p.left = c
        p
      }

      var root:ConditionOperator = new ConditionOperator(b.head._1, a, b.head._2)

      for (f <- b.tail) {
        var parent = f._1 match {
          case "&&" => new ConditionOperator("&&", null, f._2)
          case "||" => ConditionOperator("||", null, f._2)
        }

        root = appendExpression(root, parent)
      }

      root
    }

  }

  def conditionFactor:Parser[ConditionExpr] = conditionLR ^^ {
    a => new ConditionElem(a)
  } | {
    "(" ~> conditionExpr <~ ")" ^^ { e => e }
  }

  // Conditional: Typical Left-operator-Right conditionals
  def conditionLR:Parser[Condition] = positioned(expr) ~ ("<" | ">" | "==" | "!=" | "<=" | ">=" | "in") ~ positioned(expr) ^^ {
    case left ~ op ~ right => new ConditionLR(op, left, right)
  }

  /*
   * Expressions (expr)
   */
  def expr:Parser[Expr] = positioned(term) ~ rep(("+" | "-") ~ positioned(term)) ^^ {
    case a ~ List() => a                                                    // Single term (e.g. 2 * 3)
    case a ~ b => {                                                         // Multiple terms (e.g. 2 * 3 + 1)
      def appendExpression(c:Operator, p:Operator):Operator = {
        p.left = c
        p
      }

      var root:Operator = new Operator(b.head._1, a, b.head._2)

      for (f <- b.tail) {
        var parent = f._1 match {
          case "+" => new Operator("+", null, f._2)
          case "-" => Operator("-", null, f._2)
        }

        root = appendExpression(root, parent)
      }

      root
    }

  }


  def term:Parser[Expr] = positioned(multiplydividemodulo) ^^ {
    l => l
  } | factor ^^ {
    a => a
  }

  def multiplydividemodulo:Parser[Expr] = positioned(factor) ~ rep(("*" | "/" | "%") ~ factor) ^^ {
    case a ~ List() => a                                                      // Single factor    (e.g. 2)
    case a ~ b => {                                                           // Multiple factors (e.g. 2 * 3 / 4)
      def appendExpression(e:Operator, t:Operator):Operator = {
        t.left = e.right
        e.right = t
        t
      }

      var root:Operator = new Operator(b.head._1, a, b.head._2)
      var current = root

      // For each of these possible operators, build the parse tree
      for (f <- b.tail) {
        var rightOperator = f._1 match {
          case "*" => Operator("*", null, f._2)
          case "/" => Operator("/", null, f._2)
          case "%" => Operator("%", null, f._2)
        }
        current = appendExpression(current, rightOperator)
      }

      root
    }
  }

  // Examples of single factors
  def factor:Parser[Expr] = stringLit ^^ {                                    // String literal (e.g. "test")
    case str => new Str( Str.interpretStringControlChars(str) )
  } | opt("-") ~ numericLit ~ "." ~ numericLit ^^ {                           // Double (e.g. 123.456)
    case None ~ a ~ "." ~ b => new Number((a + "." + b).toDouble)
    case minus ~ a ~ "." ~ b => new Number((a + "." + b).toDouble * -1)
  } | opt("-") ~ numericLit ^^ {                                              // Integer (e.g. 123)
    case None ~ num => new Number(num.toDouble)
    case minus ~ num => new Number(num.toDouble * -1)
  } | booleanLit ^^ {                                                         // Boolean (true or false)
    case b => b
  } | createArray ^^ {                                                        // New Array (e.g. Array(1, 2, 3) )
    case a => a
  } | arrayElem ^^ {                                                          // Array element (e.g. myarray[1] )
    case ae => ae
  } | positioned(objectCreate) ^^ {                                           // New object instance (e.g. new Tree() )
    case newinstance => newinstance
  } | positioned(objectProperty) ^^ {                                         // Property name of object instance (e.g. cat.temperature )
    case objectproperty => objectproperty
  } | builtInFunction ^^ {                                                    // A built-in function reference (e.g. round(x1) )
    case builtinfunct => builtinfunct
  } | ident ^^ {                                                              // An identifier (e.g. variable name, such as "cat")
    case name => new Identifier(name)
  } | "!" ~> expr ^^ {                                                        // Negated expressions (e.g. !success )
    case e => new NegatedExpr(e)
  } | "(" ~> positioned(expr) <~ ")" ^^ { e => e }                              // Any expression wrapped in brackets


  // Property of an object instance (e.g. cat.temperature)
  def objectProperty:Parser[ObjectProperty] = ident ~ "." ~ ident ^^ {
    case instname ~ _ ~ propname => new ObjectProperty(instname, propname)
  }

  def booleanLit:Parser[Bool] = ("true" | "True" | "TRUE" | "false" | "False" | "FALSE") ^^ {
    case value => new Bool(value.toLowerCase.toBoolean)
  }

  def builtInFunction:Parser[BuiltInFunction] = (ident <~ "(") ~ exprParams <~ ")" ^^ {
    case fname ~ params => new BuiltInFunction(fname, params)
  }

  def createArray:Parser[ArrayDef] = "Array" ~ "(" ~> expr ~ rep("," ~> expr) <~ ")" ^^ {
    case firstElem ~ elemExprs => new ArrayDef(List(firstElem) ++ elemExprs)
  }

  def arrayElem:Parser[ArrayElem] = ident ~ ("[" ~> expr <~ "]") ^^ {
    case name ~ elemIdxExpr => new ArrayElem(name, elemIdxExpr)
  }

  def exprParams:Parser[List[Expr]] = expr ~ opt(rep("," ~> expr)) ^^ {
    case e1 ~ None => List(e1)
    case e1 ~ Some(e2) => List(e1) ++ e2
  }

  /*
   * Expressions (object creation/destruction)
   */
  def objectCreate:Parser[ObjectCreate] = "new" ~> ident ~ positioned(paramList) ^^ {
    case objtype ~ paramlist => new ObjectCreate(objtype, "name", paramlist)
  }



  // Parser
  def parseAll[T](p:Parser[T], in:String):ParseResult[T] = {
    phrase(p)(new lexical.Scanner(in))
  }


}
