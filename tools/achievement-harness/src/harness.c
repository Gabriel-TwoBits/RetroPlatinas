/*
 * Headless libretro frontend + rcheevos runtime shim, driven from Python (harness.py) via ctypes.
 * One emulator instance per process: libretro cores keep global state, and so does this shim.
 */
#include <dlfcn.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "libretro.h"
#include "rc_runtime.h"
#include "rc_runtime_types.h"
#include "rc_version.h"

#define MAX_OPTIONS 256
#define MAX_KEY_LEN 128
#define MAX_VALUE_LEN 256
#define MAX_PATH_LEN 4096
#define MAX_VERSION_LEN 256
#define MAX_EVENTS 4096
#define MAX_FB_WIDTH 1024
#define MAX_FB_HEIGHT 1024
#define MAX_BYTES_PER_PIXEL 4
#define MAX_FB_BYTES (MAX_FB_WIDTH * MAX_FB_HEIGHT * MAX_BYTES_PER_PIXEL)
#define RGB24_BYTES_PER_PIXEL 3
#define PS1_RA_MAIN_RAM_END 0x200000u
#define BYTE_BITS 8

#define AV_ENABLE_VIDEO 1
#define AV_ENABLE_AUDIO 2

/* Pixel unpacking: 5- and 6-bit channels are widened to 8 bits by shifting left. */
#define XRGB8888_RED_SHIFT 16
#define XRGB8888_GREEN_SHIFT 8
#define CHANNEL8_MASK 0xffu
#define RGB565_RED_SHIFT 11
#define RGB565_GREEN_SHIFT 5
#define RGB565_GREEN_MASK 0x3fu
#define RGB1555_RED_SHIFT 10
#define RGB1555_GREEN_SHIFT 5
#define CHANNEL5_MASK 0x1fu
#define CHANNEL5_TO_8_SHIFT 3
#define CHANNEL6_TO_8_SHIFT 2

enum load_result {
    LOAD_OK = 0,
    LOAD_DLOPEN_FAILED = -1,
    LOAD_MISSING_SYMBOL = -2,
    LOAD_GAME_UNREADABLE = -3,
    LOAD_GAME_SHORT_READ = -4,
    LOAD_GAME_REJECTED = -5,
};

typedef struct {
    char key[MAX_KEY_LEN];
    char value[MAX_VALUE_LEN];
} option_t;

typedef struct {
    uint64_t frame;
    int32_t type;
    uint32_t id;
    int32_t value;
} event_t;

static struct {
    void *handle;
    void (*init)(void);
    void (*set_environment)(retro_environment_t);
    void (*set_video_refresh)(retro_video_refresh_t);
    void (*set_audio_sample)(retro_audio_sample_t);
    void (*set_audio_sample_batch)(retro_audio_sample_batch_t);
    void (*set_input_poll)(retro_input_poll_t);
    void (*set_input_state)(retro_input_state_t);
    void (*get_system_info)(struct retro_system_info *);
    void (*get_system_av_info)(struct retro_system_av_info *);
    void (*set_controller_port_device)(unsigned, unsigned);
    void (*run)(void);
    size_t (*serialize_size)(void);
    bool (*serialize)(void *, size_t);
    bool (*unserialize)(const void *, size_t);
    bool (*load_game)(const struct retro_game_info *);
    void *(*get_memory_data)(unsigned);
    size_t (*get_memory_size)(unsigned);
} core;

static option_t user_options[MAX_OPTIONS];
static int user_option_count;
static option_t default_options[MAX_OPTIONS];
static int default_option_count;

static char system_dir[MAX_PATH_LEN] = ".";
static char save_dir[MAX_PATH_LEN] = ".";
static char core_version[MAX_VERSION_LEN];
static int verbose;

static enum retro_pixel_format pixel_format = RETRO_PIXEL_FORMAT_0RGB1555;
static uint8_t framebuffer[MAX_FB_BYTES];
static unsigned fb_width;
static unsigned fb_height;
static unsigned fb_bytes_per_pixel = sizeof(uint16_t);

static uint32_t input_mask;
static uint64_t frame_counter;

static rc_runtime_t runtime;
static int runtime_ready;
static event_t events[MAX_EVENTS];
static int event_count;

static const char *lookup_option(const char *key) {
    for (int i = 0; i < user_option_count; i++) {
        if (strcmp(user_options[i].key, key) == 0) {
            return user_options[i].value;
        }
    }
    for (int i = 0; i < default_option_count; i++) {
        if (strcmp(default_options[i].key, key) == 0) {
            return default_options[i].value;
        }
    }
    return NULL;
}

/* "Description; first|second|third" -> "first" is the default value. */
static void record_default(const struct retro_variable *var) {
    if (default_option_count >= MAX_OPTIONS || !var->key || !var->value) {
        return;
    }
    const char *values = strstr(var->value, "; ");
    if (!values) {
        return;
    }
    values += strlen("; ");
    option_t *opt = &default_options[default_option_count++];
    snprintf(opt->key, sizeof(opt->key), "%s", var->key);
    size_t len = strcspn(values, "|");
    if (len >= sizeof(opt->value)) {
        len = sizeof(opt->value) - 1;
    }
    memcpy(opt->value, values, len);
    opt->value[len] = '\0';
}

int h_set_option(const char *key, const char *value) {
    for (int i = 0; i < user_option_count; i++) {
        if (strcmp(user_options[i].key, key) == 0) {
            snprintf(user_options[i].value, sizeof(user_options[i].value), "%s", value);
            return 0;
        }
    }
    if (user_option_count >= MAX_OPTIONS) {
        return -1;
    }
    snprintf(user_options[user_option_count].key, MAX_KEY_LEN, "%s", key);
    snprintf(user_options[user_option_count].value, MAX_VALUE_LEN, "%s", value);
    user_option_count++;
    return 0;
}

/* Writes "key=value\n" for every option the core declared, with its effective value. */
int h_dump_options(char *out, int size) {
    int written = 0;
    for (int i = 0; i < default_option_count && written < size; i++) {
        const char *effective = lookup_option(default_options[i].key);
        written += snprintf(out + written, (size_t)(size - written), "%s=%s\n",
                            default_options[i].key, effective ? effective : "");
    }
    return written;
}

static void log_cb(enum retro_log_level level, const char *fmt, ...) {
    if (!verbose && level < RETRO_LOG_WARN) {
        return;
    }
    va_list args;
    va_start(args, fmt);
    fprintf(stderr, "[core] ");
    vfprintf(stderr, fmt, args);
    va_end(args);
}

static bool environment_cb(unsigned cmd, void *data) {
    switch (cmd) {
    case RETRO_ENVIRONMENT_GET_CAN_DUPE:
        *(bool *)data = true;
        return true;
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
        *(const char **)data = system_dir;
        return true;
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
        *(const char **)data = save_dir;
        return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT: {
        enum retro_pixel_format fmt = *(const enum retro_pixel_format *)data;
        switch (fmt) {
        case RETRO_PIXEL_FORMAT_XRGB8888:
            fb_bytes_per_pixel = sizeof(uint32_t);
            break;
        case RETRO_PIXEL_FORMAT_RGB565:
        case RETRO_PIXEL_FORMAT_0RGB1555:
            fb_bytes_per_pixel = sizeof(uint16_t);
            break;
        default:
            return false;
        }
        pixel_format = fmt;
        return true;
    }
    case RETRO_ENVIRONMENT_GET_VARIABLE: {
        struct retro_variable *var = data;
        var->value = lookup_option(var->key);
        return var->value != NULL;
    }
    case RETRO_ENVIRONMENT_SET_VARIABLES: {
        for (const struct retro_variable *var = data; var && var->key; var++) {
            record_default(var);
        }
        return true;
    }
    case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
        *(bool *)data = false;
        return true;
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
        ((struct retro_log_callback *)data)->log = log_cb;
        return true;
    case RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION:
        /* Version 0 makes cores fall back to SET_VARIABLES, whose defaults are parsed above. */
        *(unsigned *)data = 0;
        return true;
    case RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:
        return true;
    case RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE:
        if (data) {
            *(int *)data = AV_ENABLE_VIDEO | AV_ENABLE_AUDIO;
        }
        return true;
    case RETRO_ENVIRONMENT_SET_MESSAGE:
        if (verbose) {
            fprintf(stderr, "[core msg] %s\n", ((const struct retro_message *)data)->msg);
        }
        return true;
    case RETRO_ENVIRONMENT_SET_HW_RENDER:
    case RETRO_ENVIRONMENT_GET_VFS_INTERFACE:
    case RETRO_ENVIRONMENT_GET_RUMBLE_INTERFACE:
    case RETRO_ENVIRONMENT_GET_CURRENT_SOFTWARE_FRAMEBUFFER:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_V2:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_V2_INTL:
    case RETRO_ENVIRONMENT_GET_LANGUAGE:
        return false;
    case RETRO_ENVIRONMENT_SET_ROTATION:
    case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:
    case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
    case RETRO_ENVIRONMENT_SET_DISK_CONTROL_INTERFACE:
    case RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME:
    case RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO:
    case RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:
    case RETRO_ENVIRONMENT_SET_MEMORY_MAPS:
    case RETRO_ENVIRONMENT_SET_GEOMETRY:
    case RETRO_ENVIRONMENT_SET_SERIALIZATION_QUIRKS:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_DISPLAY:
        return true;
    default:
        if (verbose) {
            fprintf(stderr, "[env] unhandled cmd %u\n", cmd);
        }
        return false;
    }
}

static void video_cb(const void *data, unsigned width, unsigned height, size_t pitch) {
    if (!data) {
        /* Duplicate frame: the previous one stays in the buffer. */
        return;
    }
    size_t row_bytes = (size_t)width * fb_bytes_per_pixel;
    if (row_bytes * height > MAX_FB_BYTES) {
        return;
    }
    for (unsigned y = 0; y < height; y++) {
        memcpy(framebuffer + y * row_bytes, (const uint8_t *)data + y * pitch, row_bytes);
    }
    fb_width = width;
    fb_height = height;
}

static void audio_sample_cb(int16_t left, int16_t right) {
    (void)left;
    (void)right;
}

static size_t audio_batch_cb(const int16_t *data, size_t frames) {
    (void)data;
    return frames;
}

static void input_poll_cb(void) {}

static int16_t input_state_cb(unsigned port, unsigned device, unsigned index, unsigned id) {
    (void)index;
    if (port != 0 || (device & RETRO_DEVICE_MASK) != RETRO_DEVICE_JOYPAD) {
        return 0;
    }
    if (id == RETRO_DEVICE_ID_JOYPAD_MASK) {
        return (int16_t)input_mask;
    }
    return (int16_t)((input_mask >> id) & 1);
}

static int resolve(void **slot, const char *name) {
    *slot = dlsym(core.handle, name);
    if (!*slot) {
        fprintf(stderr, "missing symbol %s\n", name);
        return -1;
    }
    return 0;
}

void h_set_verbose(int value) { verbose = value; }

void h_set_dirs(const char *system, const char *save) {
    snprintf(system_dir, sizeof(system_dir), "%s", system);
    snprintf(save_dir, sizeof(save_dir), "%s", save);
}

int h_load(const char *core_path, const char *game_path) {
    core.handle = dlopen(core_path, RTLD_NOW | RTLD_LOCAL);
    if (!core.handle) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return LOAD_DLOPEN_FAILED;
    }
    int missing = 0;
    missing |= resolve((void **)&core.init, "retro_init");
    missing |= resolve((void **)&core.set_environment, "retro_set_environment");
    missing |= resolve((void **)&core.set_video_refresh, "retro_set_video_refresh");
    missing |= resolve((void **)&core.set_audio_sample, "retro_set_audio_sample");
    missing |= resolve((void **)&core.set_audio_sample_batch, "retro_set_audio_sample_batch");
    missing |= resolve((void **)&core.set_input_poll, "retro_set_input_poll");
    missing |= resolve((void **)&core.set_input_state, "retro_set_input_state");
    missing |= resolve((void **)&core.get_system_info, "retro_get_system_info");
    missing |= resolve((void **)&core.get_system_av_info, "retro_get_system_av_info");
    missing |= resolve((void **)&core.set_controller_port_device,
                       "retro_set_controller_port_device");
    missing |= resolve((void **)&core.run, "retro_run");
    missing |= resolve((void **)&core.serialize_size, "retro_serialize_size");
    missing |= resolve((void **)&core.serialize, "retro_serialize");
    missing |= resolve((void **)&core.unserialize, "retro_unserialize");
    missing |= resolve((void **)&core.load_game, "retro_load_game");
    missing |= resolve((void **)&core.get_memory_data, "retro_get_memory_data");
    missing |= resolve((void **)&core.get_memory_size, "retro_get_memory_size");
    if (missing) {
        return LOAD_MISSING_SYMBOL;
    }

    core.set_environment(environment_cb);
    core.init();
    core.set_video_refresh(video_cb);
    core.set_audio_sample(audio_sample_cb);
    core.set_audio_sample_batch(audio_batch_cb);
    core.set_input_poll(input_poll_cb);
    core.set_input_state(input_state_cb);

    struct retro_system_info info = {0};
    core.get_system_info(&info);
    snprintf(core_version, sizeof(core_version), "%s %s", info.library_name,
             info.library_version);

    struct retro_game_info game = {0};
    game.path = game_path;
    if (!info.need_fullpath) {
        FILE *f = fopen(game_path, "rb");
        if (!f) {
            return LOAD_GAME_UNREADABLE;
        }
        fseek(f, 0, SEEK_END);
        long size = ftell(f);
        fseek(f, 0, SEEK_SET);
        void *buf = malloc((size_t)size);
        if (!buf || fread(buf, 1, (size_t)size, f) != (size_t)size) {
            fclose(f);
            free(buf);
            return LOAD_GAME_SHORT_READ;
        }
        fclose(f);
        game.data = buf;
        game.size = (size_t)size;
    }
    if (!core.load_game(&game)) {
        fprintf(stderr, "retro_load_game failed\n");
        return LOAD_GAME_REJECTED;
    }
    core.set_controller_port_device(0, RETRO_DEVICE_JOYPAD);
    return LOAD_OK;
}

const char *h_core_version(void) { return core_version; }

const char *h_rcheevos_version(void) { return rc_version_string(); }

double h_fps(void) {
    struct retro_system_av_info av = {0};
    core.get_system_av_info(&av);
    return av.timing.fps;
}

uint8_t *h_ram(void) { return core.get_memory_data(RETRO_MEMORY_SYSTEM_RAM); }

size_t h_ram_size(void) { return core.get_memory_size(RETRO_MEMORY_SYSTEM_RAM); }

void h_set_input(uint32_t mask) { input_mask = mask; }

uint64_t h_frame(void) { return frame_counter; }

static uint32_t peek_cb(uint32_t address, uint32_t num_bytes, void *ud) {
    (void)ud;
    uint8_t *ram = h_ram();
    size_t size = h_ram_size();
    if (!ram || address >= PS1_RA_MAIN_RAM_END || (size_t)address + num_bytes > size) {
        /* Scratchpad ($200000+) is not exposed by libretro SYSTEM_RAM. */
        return 0;
    }
    uint32_t value = 0;
    for (uint32_t i = 0; i < num_bytes; i++) {
        value |= (uint32_t)ram[address + i] << (i * BYTE_BITS);
    }
    return value;
}

static void event_cb(const rc_runtime_event_t *event) {
    if (event_count >= MAX_EVENTS) {
        return;
    }
    events[event_count].frame = frame_counter;
    events[event_count].type = event->type;
    events[event_count].id = event->id;
    events[event_count].value = event->value;
    event_count++;
}

static void ensure_runtime(void) {
    if (!runtime_ready) {
        rc_runtime_init(&runtime);
        runtime_ready = 1;
    }
}

int h_ach_activate(uint32_t id, const char *memaddr) {
    ensure_runtime();
    return rc_runtime_activate_achievement(&runtime, id, memaddr, NULL, 0);
}

/* Puts every trigger back in WAITING with zeroed hits, as an emulator does after a state load. */
void h_ach_reset(void) {
    ensure_runtime();
    rc_runtime_reset(&runtime);
}

/* Puts one trigger back in WAITING with zeroed hits; -1 when no such achievement is active. */
int h_ach_reset_one(uint32_t id) {
    ensure_runtime();
    rc_trigger_t *trigger = rc_runtime_get_achievement(&runtime, id);
    if (!trigger) {
        return -1;
    }
    rc_reset_trigger(trigger);
    return 0;
}

int h_ach_state(uint32_t id) {
    ensure_runtime();
    rc_trigger_t *trigger = rc_runtime_get_achievement(&runtime, id);
    return trigger ? trigger->state : -1;
}

static int append_condset(const rc_condset_t *set, char *out, int size, int written) {
    for (const rc_condition_t *c = set->conditions; c && written < size; c = c->next) {
        written += snprintf(out + written, (size_t)(size - written), "%d:%u:%u:%d ", c->type,
                            c->required_hits, c->current_hits, c->is_true);
    }
    if (written < size) {
        written += snprintf(out + written, (size_t)(size - written), "| ");
    }
    return written;
}

/*
 * Serialises the hit counts of every condition as "type:required:current:true" tokens,
 * condsets separated by "|" (core first, then alts), in the order rcheevos stores them.
 */
int h_ach_hits(uint32_t id, char *out, int size) {
    ensure_runtime();
    rc_trigger_t *trigger = rc_runtime_get_achievement(&runtime, id);
    if (!trigger || size <= 0) {
        return -1;
    }
    out[0] = '\0';
    int written = 0;
    if (trigger->requirement) {
        written = append_condset(trigger->requirement, out, size, written);
    }
    for (const rc_condset_t *alt = trigger->alternative; alt; alt = alt->next) {
        written = append_condset(alt, out, size, written);
    }
    return written;
}

int h_events(uint64_t *frames, int32_t *types, uint32_t *ids, int32_t *values, int max) {
    int n = event_count < max ? event_count : max;
    for (int i = 0; i < n; i++) {
        frames[i] = events[i].frame;
        types[i] = events[i].type;
        ids[i] = events[i].id;
        values[i] = events[i].value;
    }
    event_count = 0;
    return n;
}

void h_run(int frames) {
    for (int i = 0; i < frames; i++) {
        core.run();
        frame_counter++;
        if (runtime_ready) {
            rc_runtime_do_frame(&runtime, event_cb, peek_cb, NULL, NULL);
        }
    }
}

/* Copies the last frame as packed RGB24: width*height, or -1 before any frame, -2 if too big. */
int h_framebuffer_rgb(uint8_t *out, int capacity, int *width, int *height) {
    if (fb_width == 0 || fb_height == 0) {
        return -1;
    }
    int pixels = (int)(fb_width * fb_height);
    if (pixels * RGB24_BYTES_PER_PIXEL > capacity) {
        return -2;
    }
    for (int i = 0; i < pixels; i++) {
        uint8_t r, g, b;
        switch (pixel_format) {
        case RETRO_PIXEL_FORMAT_XRGB8888: {
            uint32_t p;
            memcpy(&p, framebuffer + i * sizeof(p), sizeof(p));
            r = (uint8_t)((p >> XRGB8888_RED_SHIFT) & CHANNEL8_MASK);
            g = (uint8_t)((p >> XRGB8888_GREEN_SHIFT) & CHANNEL8_MASK);
            b = (uint8_t)(p & CHANNEL8_MASK);
            break;
        }
        case RETRO_PIXEL_FORMAT_RGB565: {
            uint16_t p;
            memcpy(&p, framebuffer + i * sizeof(p), sizeof(p));
            r = (uint8_t)(((p >> RGB565_RED_SHIFT) & CHANNEL5_MASK) << CHANNEL5_TO_8_SHIFT);
            g = (uint8_t)(((p >> RGB565_GREEN_SHIFT) & RGB565_GREEN_MASK) << CHANNEL6_TO_8_SHIFT);
            b = (uint8_t)((p & CHANNEL5_MASK) << CHANNEL5_TO_8_SHIFT);
            break;
        }
        case RETRO_PIXEL_FORMAT_0RGB1555:
        default: {
            uint16_t p;
            memcpy(&p, framebuffer + i * sizeof(p), sizeof(p));
            r = (uint8_t)(((p >> RGB1555_RED_SHIFT) & CHANNEL5_MASK) << CHANNEL5_TO_8_SHIFT);
            g = (uint8_t)(((p >> RGB1555_GREEN_SHIFT) & CHANNEL5_MASK) << CHANNEL5_TO_8_SHIFT);
            b = (uint8_t)((p & CHANNEL5_MASK) << CHANNEL5_TO_8_SHIFT);
            break;
        }
        }
        out[i * RGB24_BYTES_PER_PIXEL] = r;
        out[i * RGB24_BYTES_PER_PIXEL + 1] = g;
        out[i * RGB24_BYTES_PER_PIXEL + 2] = b;
    }
    *width = (int)fb_width;
    *height = (int)fb_height;
    return pixels;
}

size_t h_state_size(void) { return core.serialize_size(); }

int h_save_state(uint8_t *buf, size_t size) { return core.serialize(buf, size) ? 0 : -1; }

/* A load restarts the frame counter: trace frames count from the state a run starts at. */
int h_load_state(const uint8_t *buf, size_t size) {
    if (!core.unserialize(buf, size)) {
        return -1;
    }
    frame_counter = 0;
    return 0;
}
