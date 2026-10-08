// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#ifdef _WIN32
#define LINEWORK_EXPORT __declspec(dllexport)
#else
#define LINEWORK_EXPORT __attribute__((visibility("default")))
#endif
