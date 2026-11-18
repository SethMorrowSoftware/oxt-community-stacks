script "community.easing"
/**
Title: Easing
Author: OXT-Beyond contributors
Version: 1.0

Easing curves for smooth movement. A curve turns "how far through the
time" (0 at the start, 1 at the end) into "how far through the change":
slow at first and fast at the end, fast at first with a gentle stop, with
a bounce, and so on.

   put ezProgress(sStarted, 1200) into tT        -- 0 to 1 over 1.2 seconds
   set the loc of button "Ball" to ezBetween("40,200", "560,200", tT, "outBounce")

Every handler here starts with "ez", so that it gets in the way of no
other library's.
*/

constant kEzNames = "linear,inQuad,outQuad,inOutQuad,inCubic,outCubic,inOutCubic,inSine,outSine,inOutSine,inExpo,outExpo,inOutExpo,outBack,outElastic,outBounce"

/**
Summary: Lists the names of the curves.

Returns: The names, with commas between them. "linear" is the first.

Description:
Use <ezNames> to offer the curves in a menu, or to try each in turn.
*/
function ezNames
   return kEzNames
end ezNames

/**
Summary: How far through a change a curve is, at a moment of its time.

Parameters:
pName: The name of a curve, one of <ezNames>. Any other name is "linear".
pT: How far through the time: 0 at the start, 1 at the end. Less than 0 is 0 and more than 1 is 1.

Returns: How far through the change: 0 at the start and 1 at the end. "outBack" and "outElastic" go a little past 1 on the way.

Description:
Use <ezCurve> when you do the arithmetic yourself. <ezBetween> does it
for a number, a point, a rectangle or a colour.
*/
function ezCurve pName, pT
   local tU
   if pT is not a number then return 0
   put max(0, min(1, pT)) into pT
   put 1 - pT into tU
   switch pName
      case "inQuad"
         return pT * pT
      case "outQuad"
         return 1 - tU * tU
      case "inOutQuad"
         if pT < 0.5 then return 2 * pT * pT
         return 1 - 2 * tU * tU
      case "inCubic"
         return pT * pT * pT
      case "outCubic"
         return 1 - tU * tU * tU
      case "inOutCubic"
         if pT < 0.5 then return 4 * pT * pT * pT
         return 1 - 4 * tU * tU * tU
      case "inSine"
         return 1 - cos(pT * pi / 2)
      case "outSine"
         return sin(pT * pi / 2)
      case "inOutSine"
         return (1 - cos(pi * pT)) / 2
      case "inExpo"
         if pT = 0 then return 0
         return 2 ^ (10 * pT - 10)
      case "outExpo"
         if pT = 1 then return 1
         return 1 - 2 ^ (-10 * pT)
      case "inOutExpo"
         if pT = 0 or pT = 1 then return pT
         if pT < 0.5 then return 2 ^ (20 * pT - 10) / 2
         return (2 - 2 ^ (-20 * pT + 10)) / 2
      case "outBack"
         return 1 - 2.70158 * tU * tU * tU + 1.70158 * tU * tU
      case "outElastic"
         if pT = 0 or pT = 1 then return pT
         return 2 ^ (-10 * pT) * sin((pT * 10 - 0.75) * (2 * pi / 3)) + 1
      case "outBounce"
         return ezBounce(pT)
   end switch
   return pT
end ezCurve

private function ezBounce pT
   if pT < 1 / 2.75 then
      return 7.5625 * pT * pT
   else if pT < 2 / 2.75 then
      subtract 1.5 / 2.75 from pT
      return 7.5625 * pT * pT + 0.75
   else if pT < 2.5 / 2.75 then
      subtract 2.25 / 2.75 from pT
      return 7.5625 * pT * pT + 0.9375
   end if
   subtract 2.625 / 2.75 from pT
   return 7.5625 * pT * pT + 0.984375
end ezBounce

/**
Summary: A value part of the way from one value to another, along a curve.

Parameters:
pFrom: Where the change starts: a number, or numbers with commas between them (a point, a rectangle, a colour).
pTo: Where it ends: as many numbers as pFrom has.
pT: How far through the time: 0 at the start, 1 at the end.
pName: The name of a curve, one of <ezNames>. Left out, it is "linear".

Returns: The value at that moment, in the shape of pFrom. A number is whole where both of its ends are whole, so that a point, a rectangle or a colour can be set as it comes.

Description:
Use <ezBetween> to move, resize or recolour something a step at a time:

   set the backgroundColor of graphic "Sky" to ezBetween("20,30,80", "250,180,90", tT, "inOutSine")
*/
function ezBetween pFrom, pTo, pT, pName
   local tK, tResult, tIndex, tA, tB, tValue
   put ezCurve(pName, pT) into tK
   put 0 into tIndex
   repeat for each item tA in pFrom
      add 1 to tIndex
      put item tIndex of pTo into tB
      if tA is not a number or tB is not a number then
         put tA into tValue
      else
         put tA + (tB - tA) * tK into tValue
         if tA is an integer and tB is an integer then
            put round(tValue) into tValue
         end if
      end if
      put tValue into item tIndex of tResult
   end repeat
   return tResult
end ezBetween

/**
Summary: How far through its time something is that started a while ago.

Parameters:
pStarted: The milliseconds when it started.
pDuration: How long it takes, in milliseconds.

Returns: 0 at the start, 1 once the time is up, and the part of the time that has passed in between.

Description:
Use <ezProgress> to get the pT that <ezCurve> and <ezBetween> ask for:

   put the milliseconds into sStarted
   ...
   put ezProgress(sStarted, 800) into tT
   if tT < 1 then send "moveOn" to me in 16 milliseconds
*/
function ezProgress pStarted, pDuration
   if pStarted is not a number or pDuration is not a number or pDuration <= 0 then
      return 1
   end if
   return max(0, min(1, (the milliseconds - pStarted) / pDuration))
end ezProgress
