// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <map>
namespace boost { namespace container {
// The RGB path does not use this colormap histogram. Its required operations
// have the same sorted-key semantics using the standard associative container.
template<class K,class V> using flat_map=std::map<K,V>;
}}
