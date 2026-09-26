#include <stdio.h>
#include <string.h>

#include "rc_error.h"
#include "rc_runtime_types.h"

#define EXIT_ALL_VALID 0
#define EXIT_SOME_INVALID 1
#define EXIT_USAGE 2
#define FIRST_MEM_ADDR_ARG 1

/* Leaderboard definitions start with this prefix and parse as a whole (STA/CAN/SUB/VAL);
   achievement triggers are a single condition set. */
static const char LEADERBOARD_PREFIX[] = "STA:";

int main(int argc, char** argv) {
  int i;
  int failures = 0;

  if (argc <= FIRST_MEM_ADDR_ARG) {
    fprintf(stderr, "usage: check-mem-addr <mem_addr> [<mem_addr> ...]\n");
    return EXIT_USAGE;
  }

  for (i = FIRST_MEM_ADDR_ARG; i < argc; ++i) {
    const int is_lboard = strncmp(argv[i], LEADERBOARD_PREFIX, strlen(LEADERBOARD_PREFIX)) == 0;
    const int size = is_lboard ? rc_lboard_size(argv[i]) : rc_trigger_size(argv[i]);
    if (size < 0) {
      printf("INVALID  %s\n         %s\n", rc_error_str(size), argv[i]);
      ++failures;
    } else {
      printf("VALID    %s\n", argv[i]);
    }
  }

  return failures > 0 ? EXIT_SOME_INVALID : EXIT_ALL_VALID;
}
