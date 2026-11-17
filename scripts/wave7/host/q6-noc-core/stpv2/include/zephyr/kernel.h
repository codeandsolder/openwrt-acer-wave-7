#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <limits.h>
#define ARG_UNUSED(v) ((void)(v))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define STRINGIFY(x) #x
#define __DEBRACKET(...) __VA_ARGS__
#define __aligned(x) __attribute__((aligned(x)))
#define BIT64_MASK(n) ((n)>=64 ? UINT64_MAX : ((UINT64_C(1)<<(n))-1))
#define BIT_MASK(n) ((n)>=32 ? UINT32_MAX : ((UINT32_C(1)<<(n))-1))
