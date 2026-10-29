# Material Icons 1.7.3 独立 OHOS producer

本目录是两个独立模块 `material-icons-core`、`material-icons-extended` 的 OHOS 构建配方；不修改上游 Android/iOS 模块或主工程，不包含应用侧依赖切换。上游 fork 基准为 Compose Multiplatform Core `v1.7.3` Git 提交 `6a03ba934d30f31bf55c36d36e46aec9a7701477`。原端口取自主工程固定提交 `a2c2a1ddfc81e876ee2fe1686681aa3b00b160ac` 的 `harmony-build/ports/material-icons/`，各原始路径、长度和 SHA-256 见 [original-port-inputs.json](original-port-inputs.json)。该清单也记录已独立化的旧配方文件的迁移来源，其原 SHA 并不表示改造后的配方仍与旧 blob 相同。

`vendor/` 保存 Maven 坐标 `org.jetbrains.compose.material:material-icons-core/extended:1.7.3` 的官方 source JAR、POM、Gradle Module Metadata 原字节；URL、原取得方式、SHA 与 Apache 2.0 原文见 [legal/origins.json](legal/origins.json)、[legal/LICENSE](legal/LICENSE) 和 [source-inputs.json](source-inputs.json)。Maven 归档身份与上述 Git 提交是不同事实：生成图标尚未与 Git tree 全量逐文件比对，不能声称二者已证明一致。辅助代码参考了 FileKit fork 提交 `fc29478a7f7a9500dbb01b9d49d7a270fbcd57da` 的 `ohos/FileKitPort.py`，保留其 [MIT 许可](legal/FileKit-reference-LICENSE)；参考许可 SHA-256 为 `5ceb0f372844932c328a4d34bfb6b1903b157d4b3467c5de484bfec8e5aea7ca`。

Plan 检查两份 JAR、POM、GMM、许可、wrapper 的大小和摘要，扫描每个归档成员，按原 member 和原字节确认 core 281、extended 11105 个 common Kotlin 源及集合摘要。extended 的五组 `AddChart.kt`/`Addchart.kt` 大小写碰撞，在展开时以不同 `__case_1` / `__case_2` 父目录保留两个原文件名和字节；manifest 保留原名、staged 路径、实际路径及哈希。它们均进入各模块的 commonMain，不裁剪图标，也不对生产源添加构建守卫。

构建采用 Gradle 9.5.0、Kotlin/KGP/Compose compiler `2.4.20-0.1.0-08` 和 CPF Compose UI `1.12.0-0.1.0-11`。core 对 UI、UI graphics 和 UI unit 使用 API；extended 对同版本 core 项目使用 API，并对 UI 和 UI graphics 使用 API。标准 KGP metadata、OHOS x64 和 arm64 分阶段执行；不以替代编译或运行宣称通过。

## 构建隔离与身份

从包含本目录的完整 fork **已提交** checkout 运行。每次必须指定当前完整 `--source-sha`、正整数 `--run-id`/`--run-attempt` 和四个绝对路径 `--work`、`--repository`、`--native-home`、`--tooling`。工作目录与 staging 必须互不包含，且都必须在 fork、Native home 和 tooling 之外。Prepare 要求 work 和 staging 均不存在；Publish 也要求 staging 不存在。各阶段保留收据与日志；成功证明绑定真实零退出收据、构建指纹及对应阶段的证据，后续阶段和 Verify 均先检查证明。Publish 的 Gradle 零退出收据先接受全部发布物校验；只有校验完成后才写完整成功证明，并将该证明绑定收据和发布校验记录。独立 Verify 必须先检查完整证明，再重新核对发布物；发布中断或校验失败不能用旧 work 重试。阶段只允许认领一次，失败、中断或证据校验不通过时保留现场，换新的 work、staging 和 run attempt 后重新开始。脚本不清理任何路径，也不写入 checkout、工具 checkout、Native home 或旧 Maven 仓库。

Plan 只读本目录，输出源码摘要、预览坐标、fingerprint 和 `recipeMatchesCommit`。它可以展示尚未提交的配方，但 `recipeMatchesCommit=false` 时 Prepare 等写入阶段一律拒绝。提交后运行的配方文件集合与字节必须同 `--source-sha` 的 Git blob 完全一致。默认 group 是 `io.github.qsxs.cpf.materialicons`，两个模块版本一致：`1.7.3-cpf11-preview-<source SHA 前12位>-<run id>-<run attempt>`。fingerprint 记录配方、固定原始输入和运行身份；发布时各 publication 带 Apache 许可、上游来源与 build-provenance，根 publication 还附原始上游 sources/POM/GMM。

`--tooling` 须指向 `https://github.com/qsxs/cpf-port-tooling` 的 Git 根目录，HEAD 为 `d0cff88fd1ea2e4f08bb4409f1c802cca0c7f285`。[tooling-lock.json](tooling-lock.json) 固定 20 个工具文件的路径、长度和 SHA-256；Prepare 和后续阶段逐项校验，不依赖主工程构建配方或已有本机 Gradle 缓存。Linux 使用锁定的 `bootstrap-native.py`，从其校验过的 bundle 创建新 Native home；Windows 检查指定 Native home 中固定版本及编译器 JAR。Linux 检查 bundle 归档和 bootstrap 收据，但不会逐文件复哈解包树或完整证明编译器实际读取的所有物理输入。运行环境需要 Python 3.9 或更新版本。producer 用参数数组直接执行 Java Wrapper，不通过系统 shell；首次 Gradle wrapper/依赖下载需要网络，版本与源按配方锁定；`--offline` 仅在显式选择且隔离缓存已具备输入时使用。

以下是 Linux x86_64 命令示例，`$FORK` 为完整 fork checkout，`$TOOLING` 为上述工具 checkout；确保 `$WORK_DIR`、`$STAGING_DIR`、`$NATIVE_ROOT` 都是新的互相分离路径，JDK 17 的 `JAVA_HOME` 已设置：

```sh
export SOURCE_SHA="$(git -C "$FORK" rev-parse HEAD)"
export WORK_DIR="/tmp/icons-$RUN_ID-$RUN_ATTEMPT-work"
export STAGING_DIR="/tmp/icons-$RUN_ID-$RUN_ATTEMPT-staging"
export NATIVE_ROOT="/tmp/icons-$RUN_ID-$RUN_ATTEMPT-native"
export NATIVE_HOME="$NATIVE_ROOT/kotlin-native-prebuilt-linux-x86_64-2.4.20-0.1.0-08"
cd "$FORK"
set -- --source-sha "$SOURCE_SHA" --run-id "$RUN_ID" --run-attempt "$RUN_ATTEMPT" --work "$WORK_DIR" --repository "$STAGING_DIR" --native-home "$NATIVE_HOME" --tooling "$TOOLING"
python3 -B ohos/MaterialIconsPort.py Plan "$@"
python3 -B ohos/MaterialIconsPort.py Prepare "$@"
python3 -B "$TOOLING/toolchains/kotlin-native/2.4.20-0.1.0-08/bootstrap-native.py" --destination "$NATIVE_ROOT" --kotlin-version 2.4.20-0.1.0-08
for stage in Tasks Resolve Metadata NativeX64 NativeArm64 Publish Verify; do
    python3 -B ohos/MaterialIconsPort.py "$stage" "$@" || exit 1
done
```

每个编译阶段默认按 core、extended 顺序串行，也可用 `--module Core` / `--module Extended` 分别调用，后续阶段须满足既定顺序。Tasks 保存真实任务清单，Resolve 和编译阶段留存解析、实际编译源集合、原字节、任务输出和目标架构证据。Publish 仅向显式 staging 写入，Verify 核对根及两 ABI 的 GMM、POM、依赖边、artifact 摘要、源码 JAR、许可、来源及 KLIB 目标/非空内容。脚本与静态 Plan 本身均不代表编译、发布、独立 consumer、链接或设备运行成功；这些结果须由云端实际执行和证据分别确认。

## 首轮云端 producer 失败记录

[producer 40902885173/1](https://github.com/qsxs/cpf-port-tooling/actions/runs/40902885173/attempts/1) 使用 source commit `a29ad241d272630768a2d44c05964ee241c62e09`，在 `Metadata` 的 core 阶段退出 1：`commonizeNativeDistribution` 的 `kotlinKlibCommonizerClasspath` 未解析到 `org.jetbrains.kotlin:kotlin-klib-commonizer-embeddable:2.4.20-0.1.0-08`，日志显示只搜索了 Maven Central。该固定版本的 CPF develop POM 已只读核对存在；旧 CPF 仓 content 过滤未包含此宿主工具坐标。

本次在两个 CPF 仓增加锁定工具清单中九个此前缺失的 Kotlin `.08` 宿主工具精确版本路由；同版 stdlib、tooling-core 和 build-tools-api 原已由业务 pins 路由，公共旧版 host 传递依赖继续使用 Maven Central。路由过滤不强制选择依赖版本，也不改变业务 pins。该路由修复在第三轮 producer 的完整构建与发布校验中通过；设备运行仍未验证。

## 第二轮云端 producer 失败记录

[producer 40906194563/1](https://github.com/qsxs/cpf-port-tooling/actions/runs/40906194563/attempts/1) 使用 source commit `c43f6ec33c3c562691993b0c1e34834643a6fa58`，已经过 core 的 `commonizeNativeDistribution`，随后在 `compileCommonMainKotlinMetadata` 退出 1：`kotlinCompilerPluginClasspathMetadataCommonMain` 不能解析 `org.jetbrains.kotlin:kotlin-compose-compiler-plugin-embeddable:2.4.20-0.1.0-08`；日志显示只搜索了 Maven Central，CPF 仓过滤未包含该插件。该固定版本的 CPF develop POM 已只读核对存在，摘要与固定工具提交中的 `compiler-plugin-toolchain.json` 一致。

本次仅将该 Compose 编译插件加入两个 CPF 仓既有的宿主工具精确 `.08` 版本过滤，不修改原有九项、业务 pins 或 SDK。该插件清单位于固定工具提交 `d0cff88fd1ea2e4f08bb4409f1c802cca0c7f285`；它不在当前 20 项 tooling-lock 文件清单中。该插件路由修复在第三轮 producer 的完整构建与发布校验中通过；设备运行仍未验证。


## Material Icons 1.7.3 鸿蒙迁仓预览

- 上游 Fork：`qsxs/compose-multiplatform-core`，源码提交 `17eb10c7c46658be710f1bdc543aa9f85c96563e`；对应 Maven 官方 source JAR 和 Git tag 是分别固定的来源，生成图标与 tag 的逐项一致性尚未证明。
- 公开 Maven 根：`https://qsxs.github.io/cpf-maven/`；两个模块 group 为 `io.github.qsxs.cpf.materialicons`，同版 `1.7.3-cpf11-preview-17eb10c7c466-40908810417-1`。extended 的公开 API 依赖同版 core。
- [producer 40908810417/1](https://github.com/qsxs/cpf-port-tooling/actions/runs/40908810417/attempts/1) 使用 Gradle 9.5.0、JDK 17 和 Kotlin `2.4.20-0.1.0-08`，metadata、OHOS x64/arm64、Publish 和 Verify 均通过；完整源码 281/11105 与五组大小写映射已核。
- [Pages 提交 8eeacfbd8956](https://github.com/qsxs/cpf-maven/commit/8eeacfbd8956e372deae09ca4f3e75280e92b567) 的 280 个文件来自已核 staging；公开六份 GMM 和两份根 sources JAR 与 staging 匿名校验一致。extended sources 在整包下载中断后以 47 个区间、129 次请求组装并确认 SHA-256。
- [consumer 40915070575/1](https://github.com/qsxs/cpf-port-tooling/actions/runs/40915070575/attempts/1) 以 extended 根坐标传递解析同版 core，实际完成 metadata、OHOS x64 与 arm64 编译；14 次匿名元数据请求和选中制品摘要与 staging 匹配。证据不含 runner 输出二进制，不能独立重哈；link、runtime、物理 ARM 及 Android/iOS 回归未验证，主工程引用尚未切换。
