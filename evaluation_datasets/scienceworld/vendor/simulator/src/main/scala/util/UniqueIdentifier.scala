package util

/*
 * Generate unique sequential identifiers
 */

object UniqueIdentifier {
  var count:Long = 0

  def getNextID():Long = {
    count += 1
    return count
  }

  def reset(): Unit = {
    this.count = 0
  }
}
