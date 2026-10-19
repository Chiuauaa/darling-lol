/* Confirm whether AppKit's file panel exposes the sheet-completion API the
   Chromium/Electron Cocoa file dialog calls:
   -[NSSavePanel beginSheetModalForWindow:completionHandler:].

   When that selector is missing, Chromium's call raises
   NSInvalidArgumentException, which aborts the Riot Client UX process
   (CrBrowserMain, SIGABRT) when the user opens the game install folder picker.

   The probe inspects the class table only, so it needs no window server. It
   writes the result to a file as well as stdout so a headless run always
   leaves evidence. */
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <stdio.h>

int main(void) {
 @autoreleasepool {
  FILE *out = fopen("/Volumes/SystemRoot/home/chiuaua/darling-lol/build/"
                    "openpanel-sheet-probe.txt", "w");
  Class cls = NSClassFromString(@"NSOpenPanel");
  int control = (cls != Nil) &&
                [cls instancesRespondToSelector: @selector(setCanChooseFiles:)];
  int responds = (cls != Nil) &&
                 [cls instancesRespondToSelector:
                              @selector(beginSheetModalForWindow:completionHandler:)];
  char line[256];
  snprintf(line, sizeof line,
           "OPENPANEL_SHEET class=%p control_setCanChooseFiles=%d "
           "responds_to_sheet=%d\n",
           (void *) cls, control, responds);
  fputs(line, stdout);
  fflush(stdout);
  if (out != NULL) {
   fputs(line, out);
   fflush(out);
   fclose(out);
  }
 }
 return 0;
}
