script "oxt_community_make_fixture"
-- Makes one small stack file for the scanner's tests, from the
-- environment:
--
--    OXT_FIXTURE_OUT        the file to save
--    OXT_FIXTURE_NAME       the stack's name
--    OXT_FIXTURE_SCRIPT     the stack's script (a file to read it from)
--    OXT_FIXTURE_BUTTON     the script of a button on card 1 (a file)
--    OXT_FIXTURE_SUBSTACK   the script of a substack "Sub" (a file)
--    OXT_FIXTURE_EXTERNALS  the stack's externals property
--    OXT_FIXTURE_PASSWORD   the stack's password
--    OXT_FIXTURE_STACKFILES the stack's stackFiles property
--
-- Only the tests run this, on stacks they wrote themselves.
on startup
   local tName, tOut
   set the lockMessages to true
   put $OXT_FIXTURE_OUT into tOut
   put $OXT_FIXTURE_NAME into tName
   if tOut is empty or tName is empty then
      write "FATAL set OXT_FIXTURE_OUT and OXT_FIXTURE_NAME" & return to stdout
      quit 2
   end if
   try
      create invisible stack tName
      if $OXT_FIXTURE_SCRIPT is not empty then
         set the script of stack tName to textDecode(URL ("binfile:" & $OXT_FIXTURE_SCRIPT), "UTF-8")
      end if
      if $OXT_FIXTURE_BUTTON is not empty then
         set the defaultStack to tName
         create button "Go"
         set the script of button "Go" of stack tName to textDecode(URL ("binfile:" & $OXT_FIXTURE_BUTTON), "UTF-8")
      end if
      if $OXT_FIXTURE_SUBSTACK is not empty then
         create invisible stack "Sub"
         set the mainStack of stack "Sub" to tName
         set the script of stack "Sub" to textDecode(URL ("binfile:" & $OXT_FIXTURE_SUBSTACK), "UTF-8")
      end if
      if $OXT_FIXTURE_EXTERNALS is not empty then
         set the externals of stack tName to $OXT_FIXTURE_EXTERNALS
      end if
      if $OXT_FIXTURE_STACKFILES is not empty then
         set the stackFiles of stack tName to $OXT_FIXTURE_STACKFILES
      end if
      if $OXT_FIXTURE_PASSWORD is not empty then
         set the password of stack tName to $OXT_FIXTURE_PASSWORD
      end if
      save stack tName as tOut
      if the result is not empty then throw the result
   catch tError
      write "FATAL " & line 1 of tError & return to stdout
      quit 2
   end try
   write "MADE " & tOut & return to stdout
   quit 0
end startup
