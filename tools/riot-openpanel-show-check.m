/* Show an NSOpenPanel so its native window presentation can be checked (it
   used to render black when the driver could not create an EGL window surface
   for the panel). Prints PANEL_SHOWN before entering the run loop. */
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <stdio.h>

int main(void) {
 @autoreleasepool {
  [NSApplication sharedApplication];
  NSOpenPanel *panel = [NSOpenPanel openPanel];
  [panel setCanChooseDirectories: YES];
  [panel setCanChooseFiles: NO];
  [panel setAllowsMultipleSelection: NO];
  [panel setTitle: @"Choose the League install folder"];
  [panel makeKeyAndOrderFront: nil];

  printf("PANEL_SHOWN\n");
  fflush(stdout);

  [NSApp run];
 }
 return 0;
}
