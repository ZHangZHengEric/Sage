name := "scienceworld-scala"

version := "1.3.0"

scalaVersion := "2.12.9"

resolvers += "jetbrains-intellij-dependencies" at "https://packages.jetbrains.team/maven/p/ij/intellij-dependencies"

// Parser combinators
libraryDependencies += "org.scala-lang.modules" %% "scala-parser-combinators" % "2.0.0"

// PY4J (Java <-> Python Interoperability)
libraryDependencies += "net.sf.py4j" % "py4j" % "0.10.3"

// Set main class to be the Python Interface
Compile / mainClass := Some("scienceworld.runtime.pythonapi.PythonInterface")
