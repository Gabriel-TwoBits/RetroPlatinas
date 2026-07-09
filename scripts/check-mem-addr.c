#include <stdio.h>

#include "rc_error.h"
#include "rc_runtime_types.h"

int main(int argc, char** argv) {
  int i;
  int failures = 0;

  if (argc < 2) {
    fprintf(stderr, "usage: check-mem-addr <mem_addr> [<mem_addr> ...]\n");
    return 2;
  }

  for (i = 1; i < argc; ++i) {
    const int size = rc_trigger_size(argv[i]);
    if (size < 0) {
      printf("INVALID  %s\n         %s\n", rc_error_str(size), argv[i]);
      ++failures;
    } else {
      printf("VALID    %s\n", argv[i]);
    }
  }

  return failures > 0 ? 1 : 0;
}
