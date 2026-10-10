#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rc_error.h"
#include "rc_runtime_types.h"

#define EXIT_ALL_VALID 0
#define EXIT_SOME_INVALID 1
#define EXIT_USAGE 2
#define FIRST_MEM_ADDR_ARG 1

#define LEADERBOARD_MARKER "STA:"
/* A rich presence script spans several lines and needs a "Display:" section; a trigger or a
   leaderboard is one line. */
#define RICH_PRESENCE_MARKER "Display:"
#define LINE_BREAK '\n'
/* richpresence.c's private display type for a macro that names no Lookup, Format or built-in:
   the parser accepts it and the display then reads "[Unknown macro]...". */
#define RC_FORMAT_UNKNOWN_MACRO 103

/* The first display part naming an unknown macro, or NULL. */
static const rc_richpresence_display_part_t* find_unknown_macro(const rc_richpresence_t* rp) {
  const rc_richpresence_display_t* display;
  const rc_richpresence_display_part_t* part;

  for (display = rp->first_display; display; display = display->next) {
    for (part = display->display; part; part = part->next) {
      if (part->display_type == RC_FORMAT_UNKNOWN_MACRO) {
        return part;
      }
    }
  }
  return NULL;
}

/* 0 when the script parses and every macro resolves, 1 otherwise; prints the verdict. */
static int check_rich_presence(const char* script) {
  const int size = rc_richpresence_size(script);
  const rc_richpresence_display_part_t* unknown;
  rc_richpresence_t* rp;
  void* buffer;
  int failed;

  if (size < 0) {
    printf("INVALID  rich presence: %s\n", rc_error_str(size));
    return 1;
  }
  buffer = malloc((size_t)size);
  if (!buffer) {
    fprintf(stderr, "out of memory parsing the rich presence script\n");
    return 1;
  }
  rp = rc_parse_richpresence(buffer, script, NULL, 0);
  if (!rp) {
    printf("INVALID  rich presence: the parser returned no script\n");
    failed = 1;
  } else if ((unknown = find_unknown_macro(rp)) != NULL) {
    printf("INVALID  rich presence: unknown macro %s\n", unknown->text);
    failed = 1;
  } else {
    printf("VALID    rich presence (%d bytes parsed)\n", size);
    failed = 0;
  }
  free(buffer);
  return failed;
}

static int check_definition(const char* definition) {
  int size;

  if (strstr(definition, RICH_PRESENCE_MARKER) || strchr(definition, LINE_BREAK)) {
    return check_rich_presence(definition);
  } else if (strncmp(definition, LEADERBOARD_MARKER, strlen(LEADERBOARD_MARKER)) == 0) {
    /* STA/CAN/SUB/VAL parse as a whole. */
    size = rc_lboard_size(definition);
  } else {
    /* An achievement trigger: one condition set, optionally with alt groups. */
    size = rc_trigger_size(definition);
  }
  if (size < 0) {
    printf("INVALID  %s\n         %s\n", rc_error_str(size), definition);
    return 1;
  }
  printf("VALID    %s\n", definition);
  return 0;
}

int main(int argc, char** argv) {
  int i;
  int failures = 0;

  if (argc <= FIRST_MEM_ADDR_ARG) {
    fprintf(stderr, "usage: check-mem-addr <mem_addr | leaderboard | rich presence> [...]\n");
    return EXIT_USAGE;
  }
  for (i = FIRST_MEM_ADDR_ARG; i < argc; ++i) {
    failures += check_definition(argv[i]);
  }
  return failures > 0 ? EXIT_SOME_INVALID : EXIT_ALL_VALID;
}
