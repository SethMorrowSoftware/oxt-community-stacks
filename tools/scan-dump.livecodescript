script "oxt_community_scan_dump"
-- (tools/scan.py runs a copy of this file under a name made up for that
-- run: a stack that takes this one's name cannot be read in its place)
-- Writes what the scanner needs to know about one stack file to stdout:
-- every stack in the file, every object in each, and every script.
--
--    OXT_SCAN_FILE=<stack file> <engine> -ui tools/scan-dump.livecodescript
--
-- The stack is somebody else's program, so it is never opened and never
-- runs:
--   - messages are locked from the first line, so reading it sends it
--     nothing (no openStack, no getProp);
--   - before the file is read the engine gives up every permission but
--     reading files, and before anything in it is looked at it gives up
--     that one too. The engine only ever takes permissions away (the
--     securityPermissions), so from then on this process cannot run a
--     program, open a socket, touch a file or load a native external,
--     whatever happens. The engine does not open a stack's externals
--     until the stack is opened, and here it never is.
-- tools/scan.py runs this with no network, an empty environment and a
-- time limit as well.
--
-- The output is lines of tab-separated fields. Every value that came out
-- of the stack is the base64 of its UTF-8, so nothing in a stack can
-- forge a line:
--
--    OXTSCAN 1
--    stack  <main|sub>  <name>  <externals>  <stackFiles>  <password 0|1>  <scriptOnly 0|1>
--    object <type>  <id>  <name>  <path>  <readable 0|1>  <script>  <kind>  <behavior>  <fileName>
--    END <number of stack lines> <number of object lines>
--
-- (each object line belongs to the stack line before it; a stack's own
-- script is an object line of type "stack"; readable is 0 when the
-- engine would not give the script, which is how a stack with a password
-- shows). A dump without its END line,
-- or with the wrong counts on it, is a failed dump: the scanner refuses
-- the stack. Exit code 0 on success, 3 when the file could not be read as
-- a stack, 2 for a mistake in how this was run.

local sSeen, sStacks, sObjects

on startup
   local tFile, tName, tSub, tError
   set the lockMessages to true
   put $OXT_SCAN_FILE into tFile
   if tFile is empty then
      write "FATAL set OXT_SCAN_FILE to a stack file" & return to stdout
      quit 2
   end if
   set the securityPermissions to "disk"
   if the securityPermissions is not "disk" then
      write "FATAL the engine kept permissions it was told to give up" & return to stdout
      quit 2
   end if
   write "OXTSCAN 1" & return to stdout
   try
      put the short name of stack tFile into tName
   catch tError
      write "ERROR" & tab & "load" & return to stdout
      quit 3
   end try
   set the lockMessages to true
   -- The stack that was read must be the one in the file: a file whose
   -- stack has the name of one that is already here (this one) gives
   -- that one's name back, and its scripts would be read for the file's
   if the effective fileName of stack tName is not tFile then
      write "ERROR" & tab & "name" & return to stdout
      quit 3
   end if
   set the securityPermissions to empty
   if the securityPermissions is not empty then
      write "FATAL the engine kept permissions it was told to give up" & return to stdout
      quit 2
   end if
   put 0 into sStacks
   put 0 into sObjects
   try
      scanStack the long id of stack tName, "main"
      repeat for each line tSub in the substacks of stack tName
         scanStack the long id of stack tSub of stack tName, "sub"
      end repeat
   catch tError
      write "ERROR" & tab & "read" & return to stdout
      quit 3
   end try
   write "END" && sStacks && sObjects & return to stdout
   quit 0
end startup

private function enc pValue
   local tOut
   put base64Encode(textEncode(pValue, "UTF-8")) into tOut
   replace return with empty in tOut
   return tOut
end enc

private command scanStack pStack, pRole
   local tPassword, tScriptOnly, tCard, tGroup, tError
   if the effective fileName of pStack is not $OXT_SCAN_FILE then
      throw "a stack that is not the file's"
   end if
   put 0 into tPassword
   try
      if the password of pStack is not empty then put 1 into tPassword
   catch tError
      put 1 into tPassword
   end try
   put 0 into tScriptOnly
   if the scriptOnly of pStack then put 1 into tScriptOnly
   write "stack" & tab & pRole & tab & enc(the short name of pStack) & tab & enc(the externals of pStack) \
         & tab & enc(the stackFiles of pStack) & tab & tPassword & tab & tScriptOnly & return to stdout
   add 1 to sStacks
   put empty into sSeen
   scanObject pStack, "stack"
   repeat with tCardNumber = 1 to the number of cards of pStack
      put the long id of card tCardNumber of pStack into tCard
      scanObject tCard, "card" && tCardNumber
      scanControls tCard, "card" && tCardNumber
   end repeat
   -- (groups that are on no card)
   repeat with tGroupNumber = 1 to the number of backgrounds of pStack
      put the long id of background tGroupNumber of pStack into tGroup
      if sSeen[the id of tGroup] then next repeat
      scanControl tGroup, "on no card"
   end repeat
end scanStack

private command scanControls pOwner, pPath
   repeat with tNumber = 1 to the number of controls of pOwner
      scanControl the long id of control tNumber of pOwner, pPath
   end repeat
end scanControls

private command scanControl pControl, pPath
   if sSeen[the id of pControl] then exit scanControl
   put true into sSeen[the id of pControl]
   scanObject pControl, pPath
   -- (the controls of a card count the ones inside its groups, each
   -- once; a group on no card is walked here)
   if word 1 of the name of pControl is "group" and pPath is "on no card" then
      scanControls pControl, pPath
   end if
end scanControl

private command scanObject pObject, pPath
   local tType, tScript, tKind, tBehavior, tFile, tError, tReadable
   put word 1 of the name of pObject into tType
   -- (an imported HyperCard stack names its controls "card button" and
   -- "bkgnd field")
   if tType is among the items of "card,bkgnd,background" and word 2 of the name of pObject is among \
         the items of "button,field,image,graphic,scrollbar,player,group,widget,EPS" then
      put word 2 of the name of pObject into tType
   end if
   put 1 into tReadable
   try
      put the script of pObject into tScript
   catch tError
      -- (a script the engine will not show: the stack has a password)
      put empty into tScript
      put 0 into tReadable
   end try
   if tType is "widget" then
      try
         put the kind of pObject into tKind
      catch tError
         put "?" into tKind
      end try
   end if
   try
      put the behavior of pObject into tBehavior
   catch tError
      put empty into tBehavior
   end try
   if tType is among the items of "image,player" then
      try
         put the fileName of pObject into tFile
      catch tError
         put empty into tFile
      end try
   end if
   write "object" & tab & tType & tab & the id of pObject & tab & enc(the short name of pObject) \
         & tab & enc(pPath) & tab & tReadable & tab & enc(tScript) & tab & enc(tKind) & tab & enc(tBehavior) \
         & tab & enc(tFile) & return to stdout
   add 1 to sObjects
end scanObject
