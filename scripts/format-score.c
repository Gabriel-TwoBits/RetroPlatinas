#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "rc_client.h"
#include "rc_runtime_types.h"

#define EXIT_OK 0
#define EXIT_USAGE 2
#define FORMAT_ARG 1
#define FIRST_SCORE_ARG 2
#define DECIMAL_BASE 10

/* Prints each score as rc_client displays it for a leaderboard of the given format, one per line. */
int main(int argc, char** argv) {
  char buffer[RC_CLIENT_LEADERBOARD_DISPLAY_SIZE];
  int format;
  int i;

  if (argc <= FIRST_SCORE_ARG) {
    fprintf(stderr, "usage: format-score <format> <score> [<score> ...]\n");
    return EXIT_USAGE;
  }

  format = rc_parse_format(argv[FORMAT_ARG]);
  for (i = FIRST_SCORE_ARG; i < argc; ++i) {
    rc_format_value(buffer, sizeof(buffer), (int32_t)strtoll(argv[i], NULL, DECIMAL_BASE), format);
    printf("%s\n", buffer);
  }

  return EXIT_OK;
}
