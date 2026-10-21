/* Copyright 2026 The xLLM Authors. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
==============================================================================*/

#pragma once

#include <string>
#include <string_view>

#if defined(USE_MLU)
#include <cnpx.h>
#endif

namespace xllm::performance_analysis {

inline constexpr char kDomainName[] = "XLLM_PERF_ANALYSIS";

namespace detail {

#if defined(USE_MLU)
inline cnpxDomainHandle_t Domain() {
  static cnpxDomainHandle_t domain = cnpxDomainCreate(kDomainName);
  return domain;
}
#endif

}  // namespace detail

// 用一个线程内 RAII Range 包围目标模块；disabled 时不产生 CNPX 开销。
class ScopedModuleRange final {
 public:
  explicit ScopedModuleRange(bool enabled, std::string_view range_name) {
#if defined(USE_MLU)
    if (enabled) {
      const std::string message(range_name);
      cnpxDomainRangePush(detail::Domain(), message.c_str());
      active_ = true;
    }
#else
    static_cast<void>(enabled);
    static_cast<void>(range_name);
#endif
  }

  ~ScopedModuleRange() {
#if defined(USE_MLU)
    if (active_) {
      cnpxDomainRangePop(detail::Domain());
    }
#endif
  }

  ScopedModuleRange(const ScopedModuleRange&) = delete;
  ScopedModuleRange& operator=(const ScopedModuleRange&) = delete;
  ScopedModuleRange(ScopedModuleRange&&) = delete;
  ScopedModuleRange& operator=(ScopedModuleRange&&) = delete;

 private:
  bool active_ = false;
};

}  // namespace xllm::performance_analysis
