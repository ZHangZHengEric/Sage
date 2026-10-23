package scienceworld.environments

import scienceworld.objects.livingthing.animals.{Animal, Bee}
import scienceworld.objects.containers.{BookShelf, CeramicCup, Container, FlowerPot, GlassCup, GlassJar, Jug, MetalPot, Sewer, TinCup, WoodBowl, WoodCup}
import scienceworld.objects.containers.furniture.{Bed, BeeHive, Chair, Closet, Couch, Counter, Cupboard, Desk, SteelTable, WoodTable}
import scienceworld.objects.devices.{Axe, Bathtub, BlastFurnace, Freezer, Fridge, Lighter, Oven, Shovel, Sink, StopWatch, Stove, Thermometer, Toilet, UltraColdFreezer}
import scienceworld.objects.electricalcomponent.{Battery, LightBulb, SolarPanel, Switch, Wire}
import scienceworld.objects.environmentoutside.{FirePit, Fountain}
import scienceworld.objects.livingthing.plant.{AppleTree, OrangeTree, PeaPlant, PeachTree, Plant, Soil}
import scienceworld.objects.location.{Location, Outside, Room, Universe}
import scienceworld.objects.misc.{ForkMetal, ForkPlastic, InclinedPlane, Picture}
import scienceworld.objects.portal.Door
import scienceworld.objects.substance.food.{Apple, Banana, Orange, OrangeJuice, Potato}
import scienceworld.objects.substance.paint.{BluePaint, GreenPaint, OrangePaint, RedPaint, VioletPaint, YellowPaint}
import scienceworld.objects.substance.{Soap, SodiumChloride, Wood}
import scienceworld.objects.taskitems.{AnswerBox, UnknownSubstanceElectricalConductivity}
import scienceworld.properties.{PlasticProp, SandpaperProp}
import scienceworld.struct.EnvObject

import scala.util.Random


object RoomMaker {

  /*
 * Bathroom
 */
  def mkBathroom(includeBathtub:Boolean = true, sewer:EnvObject): Location = {
    val room = new Room("bathroom")

    // Sink
    val sink = new Sink(drainsTo = Some(sewer))
    room.addObject(sink)

    // Toilet
    val toilet = new Toilet(drainsTo = sewer)
    room.addObject(toilet)

    // Bathtub
    if (includeBathtub) {
      val bathtub = new Bathtub(drainsTo = Some(sewer))
      room.addObject(bathtub)
    }

    // Glass cup?
    val cup = new GlassCup()
    room.addObject(cup)


    // Decoration
    val randomPicture = Picture.mkRandom()
    room.addObject(randomPicture)


    // Return
    room
  }


  def mkBedroom():Location = {
    val room = new Room("bedroom")

    val bed = new Bed()
    room.addObject(bed)

    val table = new WoodTable()
    room.addObject(table)

    val closet = new Closet()
    room.addObject(closet)

    // Decoration
    val randomPicture = Picture.mkRandom()
    room.addObject(randomPicture)

    // Bookshelf
    if (Random.nextBoolean() == true) {
      room.addObject( BookShelf.mkRandom())
    }

    // Return
    room
  }


  /*
   * Living Room
   */
  def mkLivingRoom():Location = {
    val room = new Room("living room")

    // Couch
    val couch = new Couch()
    room.addObject(couch)

    // Chair
    val chair = new Chair()
    room.addObject(chair)

    // Desk/Table?
    val table = mkRandomTable()
    room.addObject(table)

    // Decoration
    val randomPicture = Picture.mkRandom()
    room.addObject(randomPicture)

    // Bookshelf
    if (Random.nextBoolean() == true) {
      room.addObject( BookShelf.mkRandom())
    }


    // Return
    room
  }


  /*
   * Kitchen
   */
  def mkKitchen(sewer:EnvObject):Location = {
    val room = new Room("kitchen")

    // Objects

    // Major appliances/devices
    val sink = new Sink(drainsTo = Some(sewer))
    room.addObject(sink)

    val stove = new Stove()
    room.addObject(stove)

    val fridge = new Fridge()
    room.addObject(fridge)

    val freezer = new Freezer()
    room.addObject(freezer)

    val oven = new Oven()
    room.addObject(oven)


    // Containers
    val cupboard = new Cupboard()
    room.addObject(cupboard)

    cupboard.addObject( new MetalPot )
    cupboard.addObject( new TinCup() )
    cupboard.addObject( new CeramicCup() )

    val counter = new Counter()
    room.addObject(counter)

    val bowl = new WoodBowl()
    counter.addObject(bowl)

    // Foods
    val apple = new Apple()
    bowl.addObject(apple)

    bowl.addObject( new Banana() )
    bowl.addObject( new Orange() )
    bowl.addObject( new Potato() )


    // Another container
    val cup2 = new WoodCup()
    cup2.addObject( new OrangeJuice() )
    fridge.addObject(cup2)

    // A Thermometer
    val thermometer = new Thermometer()
    room.addObject(thermometer)


    // Random picture
    room.addObject( Picture.mkRandom() )

    // Table
    val table = new WoodTable()
    room.addObject( table )

    // Cup on table
    table.addObject( new GlassCup() )

    // Chair
    val chair = new Chair()
    room.addObject(chair)

    // Lighter
    val lighter = new Lighter()
    room.addObject(lighter)

    // Salt
    val jar = new GlassJar()
    jar.addObject(new SodiumChloride())
    room.addObject(jar)

    // Soap
    room.addObject(new Soap())

    room.addObject(new StopWatch())

    // Return
    room
  }


  /*
   * Workshop
   */
  def mkWorkshop(): Room = {
    // House
    val room = new Room("workshop")

    // Table
    val table = new WoodTable()
    room.addObject( table )

    // Electrical
    val lightColors = Random.shuffle(List("red", "green", "blue", "yellow", "orange", "violet"))

    val lightbulb1 = new LightBulb(lightColors(0))
    //lightbulb1.name = "light bulb 1"
    table.addObject(lightbulb1)

    val lightbulb2 = new LightBulb(lightColors(1))
    //lightbulb2.name = "light bulb 2"
    table.addObject(lightbulb2)

    val lightbulb3 = new LightBulb(lightColors(2))
    //lightbulb3.name = "light bulb 3"
    table.addObject(lightbulb3)


    val wireColors = Random.shuffle(List("red", "green", "blue", "yellow", "orange", "black"))

    val wire1 = new Wire()
    wire1.name = wireColors(0) + " wire"
    table.addObject(wire1)

    val wire2 = new Wire()
    wire2.name = wireColors(1) + " wire"
    table.addObject(wire2)

    val wire3 = new Wire()
    wire3.name = wireColors(2) + " wire"
    table.addObject(wire3)

    val switch = new Switch()
    table.addObject(switch)

    val battery = new Battery()
    table.addObject(battery)


    // Ultra low temperature freezer
    room.addObject(new UltraColdFreezer)

    // Add a randomly generated substance that may or may not be electrically conductive
    /*
    val unknownSubstance = UnknownSubstanceElectricalConductivity.mkRandomSubstanceElectricalConductive()
    table.addObject(unknownSubstance)
     */
    /*
    // Add one metallic and one non-metallic object
    room.addObject(new ForkMetal())
    room.addObject(new ForkPlastic())

    // Answer box
    room.addObject( new AnswerBox("green") )
    room.addObject( new AnswerBox("red") )
    */

    //##
    /*
    val inclinedPlane1 = new InclinedPlane(angleDeg = 45, surfaceMaterial = new SandpaperProp())
    room.addObject(inclinedPlane1)

    val inclinedPlane2 = new InclinedPlane(angleDeg = 45, surfaceMaterial = new PlasticProp())
    room.addObject(inclinedPlane2)
     */

    // TODO: Task: Which inclined plane has the steepest angle?

    // Return
    room
  }

  /*
   * Greenhouse
   */
  def mkGreenhouse(sewer:EnvObject): Room = {
    // House
    val room = new Room("greenhouse")


    // Water jug
    val waterJug = new Jug()
    room.addObject(waterJug)

/*
    // debug (plant)
    val plant1 = new OrangeTree()
    //plant1.name = "plant 1"
    val soil1 = new Soil()
    val flowerpot1 = new FlowerPot()
    flowerpot1.name = "flower pot 1"

    flowerpot1.addObject(soil1)
    flowerpot1.addObject(plant1)
    room.addObject(flowerpot1)


    // debug (plant)
    val plant2 = new AppleTree()
    //plant2.name = "plant 2"
    val soil2 = new Soil()
    val flowerpot2 = new FlowerPot()
    flowerpot2.name = "flower pot 2"

    flowerpot2.addObject(soil2)
    flowerpot2.addObject(plant2)
    room.addObject(flowerpot2)

    // debug (plant)
    val plant3 = new PeachTree()
    //plant3.name = "plant 3"
    val soil3 = new Soil()
    val flowerpot3 = new FlowerPot()
    flowerpot3.name = "flower pot 3"

    flowerpot3.addObject(soil3)
    flowerpot3.addObject(plant3)
    room.addObject(flowerpot3)


    val plant4 = new PeachTree()
    //plant3.name = "plant 3"
    val soil4 = new Soil()
    val flowerpot4 = new FlowerPot()
    flowerpot4.name = "flower pot 4"

    flowerpot4.addObject(soil4)
    flowerpot4.addObject(plant4)
    room.addObject(flowerpot4)


    val plant5 = new OrangeTree()
    //plant3.name = "plant 3"
    val soil5 = new Soil()
    val flowerpot5 = new FlowerPot()
    flowerpot5.name = "flower pot 5"

    flowerpot5.addObject(soil5)
    flowerpot5.addObject(plant5)
    room.addObject(flowerpot5)
*/
/*
    val flowerpot5 = new FlowerPot()
    flowerpot5.name = "flower pot 5"
    flowerpot5.addObject(new Soil())
    flowerpot5.addObject(new PeaPlant())
    room.addObject(flowerpot5)

    val flowerpot6 = new FlowerPot()
    flowerpot6.name = "flower pot 6"
    flowerpot6.addObject(new Soil())
    flowerpot6.addObject(new PeaPlant())
    room.addObject(flowerpot6)
*/

    val beehive = new BeeHive()

    val numBees = 5
    for (i <- 0 until numBees) {
      val bee = new Bee()
      bee.name = "bee " + i
      beehive.addObject(bee)
    }
    room.addObject(beehive)





    // Also add a sink, to fill up the water jug
    val sink = new Sink(drainsTo=Some(sewer) )
    room.addObject(sink)

    //## DEBUG
    // Answer box
    //room.addObject( new AnswerBox("blue") )


    // Return
    room
  }

  // Art studio for paint mixing
  def mkArtStudio():Room = {
    val room = new Room("art studio")

    // Table
    val table = new WoodTable()
    room.addObject(table)

    // Something to mix with
    val mixingContainers = Random.shuffle( List(new GlassCup(), new WoodBowl(), new Jug()) )
    table.addObject( mixingContainers(0) )

    // Paints
    val paints1 = Array(new RedPaint, new BluePaint, new YellowPaint)
    for (paint <- paints1) {
      val woodcup = new WoodCup()
      woodcup.addObject(paint)
      room.addObject(woodcup)
    }

    // Also add a cupboard with more paint
    val cupboard = new Cupboard()
    room.addObject(cupboard)
    val paints2 = Array(new RedPaint, new BluePaint, new YellowPaint) //, new GreenPaint, new VioletPaint, new OrangePaint)
    for (paint <- paints2) {
      val woodcup = new WoodCup()
      woodcup.addObject(paint)
      cupboard.addObject(woodcup)
    }
    cupboard.name = "large cupboard"


    // Return
    room
  }


  /*
   * Outside
   */
  def mkOutside():Outside = {
    val outside = new Outside()

    outside.addObject( new FirePit() )
    outside.addObject( new Wood() )
    outside.addObject( new Axe() )
    outside.addObject( new Fountain() )

    //outside.addObject( new Animal() )

    return outside
  }


  /*
   * Foundry
   */
  def mkFoundry(sewer:Sewer):Room = {
    val foundry = new Room("foundry")

    foundry.addObject(new BlastFurnace())
    foundry.addObject(new Sink( drainsTo=Some(sewer)  ))
    foundry.addObject(new SteelTable() )

    // Return
    foundry
  }

  /*
   * Helper functions
   */
  def mkDoor(location1:Location, location2:Location, isOpen:Boolean = false) {
    val door = new Door(isOpen, location1, location2)
    location1.addPortal(door)
    location2.addPortal(door)
  }

  def mkRandomTable():EnvObject = {
    val numOptions = 3
    val randIdx = Random.nextInt(numOptions)

    if (randIdx == 0) return new WoodTable()
    if (randIdx == 1) return new SteelTable()
    if (randIdx == 2) return new Desk()

    // Default
    return new WoodTable()
  }

}




object BuildingMaker {

  def mkRandomHouse(universe:Universe, sewer:Sewer): Unit = {
    // Rooms
    val roomKitchen = RoomMaker.mkKitchen(sewer)
    universe.addObject(roomKitchen)

    val roomLivingRoom = RoomMaker.mkLivingRoom()
    universe.addObject(roomLivingRoom)

    val roomBedroom = RoomMaker.mkBedroom()
    universe.addObject(roomBedroom)

    // Bathroom
    val roomBathroom = RoomMaker.mkBathroom(includeBathtub = true, sewer)
    universe.addObject(roomBathroom)

    // Workshop
    val roomWorkshop = RoomMaker.mkWorkshop()
    universe.addObject(roomWorkshop)

    // Greenhouse
    val roomGreenhouse = RoomMaker.mkGreenhouse(sewer)
    universe.addObject(roomGreenhouse)

    // Art studio
    val roomArtStudio = RoomMaker.mkArtStudio()
    universe.addObject(roomArtStudio)


    // Hallway
    val roomHallway = new Room("hallway")
    roomHallway.addObject( Picture.mkRandom() )
    universe.addObject(roomHallway)


    // Outside
    val outside = RoomMaker.mkOutside()
    universe.addObject(outside)

    // Foundry
    val foundry = RoomMaker.mkFoundry(sewer)
    universe.addObject(foundry)

    // Randomly put a shovel in either the greenhouse or outside
    // Shovel
    val shovel = new Shovel()
    if (Random.nextInt(2) == 1) {
      roomGreenhouse.addObject(shovel)
    } else {
      outside.addObject(shovel)
    }


    // Doors
    RoomMaker.mkDoor(roomKitchen, roomHallway)
    RoomMaker.mkDoor(roomLivingRoom, roomHallway)
    RoomMaker.mkDoor(roomBedroom, roomHallway)
    RoomMaker.mkDoor(roomBathroom, roomKitchen)
    RoomMaker.mkDoor(roomWorkshop, roomHallway)
    RoomMaker.mkDoor(roomGreenhouse, roomHallway)
    RoomMaker.mkDoor(roomArtStudio, roomHallway)

    RoomMaker.mkDoor(roomKitchen, outside)
    RoomMaker.mkDoor(roomGreenhouse, outside)

    RoomMaker.mkDoor(foundry, outside)

  }



}
