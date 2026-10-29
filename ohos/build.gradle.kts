import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.security.MessageDigest
import org.gradle.api.Task
import org.gradle.api.artifacts.component.ModuleComponentIdentifier
import org.gradle.api.artifacts.component.ProjectComponentIdentifier
import org.gradle.api.artifacts.result.ResolvedDependencyResult
import org.gradle.api.artifacts.result.UnresolvedDependencyResult
import org.gradle.api.publish.PublishingExtension
import org.gradle.api.publish.maven.MavenPublication
import org.gradle.api.publish.maven.tasks.PublishToMavenRepository
import org.gradle.jvm.tasks.Jar
import org.jetbrains.kotlin.gradle.dsl.KotlinMultiplatformExtension
import org.jetbrains.kotlin.gradle.tasks.KotlinNativeCompile

plugins {
    kotlin("multiplatform") apply false
    kotlin("plugin.compose") apply false
}

fun readMap(path: File) = (JsonSlurper().parse(path) as Map<*, *>).entries.associate { it.key.toString() to it.value }
fun asMap(value: Any?) = (value as Map<*, *>).entries.associate { it.key.toString() to requireNotNull(it.value) }
fun digest(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
fun sha(path: File) = digest(path.readBytes())
fun leaves(path: File): List<File> = if (path.isDirectory) path.walkTopDown().filter(File::isFile).toList() else listOf(path)
fun records(files: Iterable<File>) = files.filter(File::isFile).distinct().sortedBy { it.path }.map {
    mapOf("path" to it.absolutePath, "size" to it.length(), "sha256" to sha(it))
}

val config = readMap(file("port-config.json"))
val modules = asMap(config.getValue("modules"))
val sourceInputs = asMap(readMap(file("source-inputs.json")).getValue("modules"))
val pins = readMap(file("dependency-pins.json"))
val metadataPins = readMap(file("metadata-pins.json"))
val fingerprint = providers.gradleProperty("portFingerprint").get()
val localProjectGavs = modules.map { (module, value) ->
    val model = asMap(value)
    "${model.getValue("group")}:$module:${providers.gradleProperty("portVersion").get()}"
}.toSet()
val work = file(providers.gradleProperty("portWork").get()).canonicalFile
val repository = file(providers.gradleProperty("portRepository").get()).canonicalFile
val portVersion = providers.gradleProperty("portVersion").get()
val manifestFile = work.resolve("source-manifest.json")
val manifest = readMap(manifestFile)
check(manifest["fingerprint"] == fingerprint)
layout.buildDirectory.set(work.resolve("build/root"))

fun evidence(name: String, value: Any) {
    val target = work.resolve("evidence/$name.json")
    target.parentFile.mkdirs()
    target.writeText(JsonOutput.prettyPrint(JsonOutput.toJson(value)) + "\n")
}

fun resolution(child: Project) = listOf("commonMainResolvableDependenciesMetadata", "ohosX64CompileKlibraries", "ohosArm64CompileKlibraries").map { name ->
    val configuration = child.configurations.getByName(name)
    val metadata = name.endsWith("ResolvableDependenciesMetadata")
    mapOf("configuration" to name, "edges" to configuration.incoming.resolutionResult.allDependencies.map { edge ->
        if (edge !is ResolvedDependencyResult) throw GradleException("Unresolved MaterialIcons dependency: $edge", (edge as? UnresolvedDependencyResult)?.failure)
        mapOf("from" to edge.from.id.displayName, "requested" to edge.requested.displayName, "selected" to edge.selected.id.displayName)
    }, "artifacts" to configuration.incoming.artifacts.artifacts.map { artifact ->
        val id = artifact.id.componentIdentifier
        val attrs = artifact.variant.attributes.keySet().associate { it.name to artifact.variant.attributes.getAttribute(it).toString() }
        when (id) {
            is ModuleComponentIdentifier -> {
                val ga = "${id.group}:${id.module}"
                check((if (metadata) metadataPins[ga] ?: pins[ga] else pins[ga]) == id.version) { "Unpinned MaterialIcons artifact: $id" }
                check(!id.module.startsWith("material-icons-")) { "External upstream icons must not replace the two source projects: $id" }
                if (metadataPins.containsKey(ga)) {
                    val common = attrs["org.gradle.usage"] == "kotlin-metadata" && attrs["org.jetbrains.kotlin.platform.type"] == "common"
                    val javaAlias = ga == "androidx.arch.core:core-common" && id.version == "2.2.0" &&
                        attrs["org.gradle.usage"] in listOf("java-api", "java-runtime") &&
                        attrs["org.jetbrains.kotlin.platform.type"] in listOf(null, "jvm") && attrs["org.gradle.category"] == "library"
                    check(metadata && (common || javaAlias) && attrs["org.jetbrains.kotlin.native.target"] == null) {
                        "Metadata supplement selected outside common metadata: $id"
                    }
                }
            }
            is ProjectComponentIdentifier -> check(child.name == "material-icons-extended" && id.projectPath == ":material-icons-core") {
                "Unexpected MaterialIcons project artifact: $id"
            }
            else -> error("Unexpected MaterialIcons component: $id")
        }
        mapOf("component" to id.displayName, "attributes" to attrs, "files" to records(leaves(artifact.file)))
    })
}

subprojects {
    val child = this
    val module = name
    val model = asMap(modules.getValue(module))
    val sourceInput = asMap(sourceInputs.getValue(module))
    group = model.getValue("group").toString()
    version = portVersion
    layout.buildDirectory.set(work.resolve("build/$module"))
    plugins.withId("org.jetbrains.kotlin.multiplatform") {
        extensions.configure<KotlinMultiplatformExtension> {
            ohosX64()
            ohosArm64()
            sourceSets {
                val commonMain by getting {
                    // 两份官方 archive 的全部 common Kotlin 原字节进入各自独立模块。
                    kotlin.setSrcDirs(listOf(work.resolve("sources/$module/commonMain")))
                    dependencies {
                        if (module == "material-icons-extended") api(project(":material-icons-core"))
                        listOf("ui", "ui-graphics").forEach { api("org.jetbrains.compose.ui:$it:${config.getValue("compose")}") }
                        if (module == "material-icons-core") api("org.jetbrains.compose.ui:ui-unit:${config.getValue("compose")}")
                    }
                }
                listOf("ohosX64Main", "ohosArm64Main").forEach {
                    getByName(it).dependsOn(commonMain)
                    getByName(it).kotlin.setSrcDirs(emptyList<File>())
                }
                matching { it.name.endsWith("Test") }.configureEach { kotlin.setSrcDirs(emptyList<File>()) }
            }
        }
        configurations.configureEach {
            val metadata = name.endsWith("ResolvableDependenciesMetadata") || name == "allSourceSetsCompileDependenciesMetadata"
            val runtime = metadata || name.endsWith("CompileKlibraries") || name.endsWith("CompilationDependenciesMetadata")
            if (runtime && !name.contains("Test", ignoreCase = true)) resolutionStrategy.eachDependency {
                val ga = "${requested.group}:${requested.name}"
                if ("$ga:${requested.version}" !in localProjectGavs) {
                    val fixed = (if (metadata) metadataPins[ga] ?: pins[ga] else pins[ga])?.toString()
                        ?: error("Unpinned MaterialIcons dependency: $requested")
                    if (requested.version != fixed) useVersion(fixed)
                }
            }
        }
        fun recordStage(name: String, compilerName: String, stage: String, metadata: Boolean) {
            tasks.register(name) {
                dependsOn(compilerName)
                if (metadata) dependsOn("allMetadataJar")
                outputs.upToDateWhen { false }
                doLast {
                    val compiler = tasks.getByName(compilerName) as KotlinNativeCompile
                    val sources = compiler.sources.files.filter { it.isFile && it.extension == "kt" }.map { it.canonicalFile }.toSet()
                    val sourceMembers = (manifest.getValue("members") as List<*>).map(::asMap).filter { it["module"] == module && it["compile"] == true }
                    val sourceRoot = work.resolve("sources/$module").canonicalFile
                    val expectedMembers = sourceMembers.associateBy { member ->
                        val staged = sourceRoot.resolve(member.getValue("stagedPath").toString()).canonicalFile
                        check(staged == file(member.getValue("path")).canonicalFile && staged.toPath().startsWith(sourceRoot.toPath()))
                        staged
                    }
                    check(expectedMembers.size == sourceMembers.size && sourceMembers.map { it.getValue("member") }.toSet().size == sourceMembers.size)
                    val expected = expectedMembers.mapValues { it.value.getValue("sha256").toString() }
                    check(expected.size == (model.getValue("sourceCount") as Number).toInt())
                    check(sources == expected.keys && expected.all { (path, hash) -> sha(path) == hash }) {
                        "Complete MaterialIcons source closure or original bytes differ: $module"
                    }
                    val sourceRows = sources.map { path -> sortedMapOf<String, Any>(
                        "member" to expectedMembers.getValue(path).getValue("member"),
                        "size" to path.length(), "sha256" to sha(path),
                    ) }.sortedBy { it.getValue("member").toString() }
                    val sourceSetSha = digest(JsonOutput.toJson(sourceRows).toByteArray(Charsets.UTF_8))
                    check(sourceSetSha == sourceInput.getValue("sourceSetSha256")) { "MaterialIcons compiler source-set digest differs: $module" }
                    val stagedRows = sources.map { path -> sortedMapOf<String, Any>(
                        "member" to expectedMembers.getValue(path).getValue("member"),
                        "stagedPath" to expectedMembers.getValue(path).getValue("stagedPath"),
                    ) }.sortedBy { it.getValue("member").toString() }
                    val stagedMappingSha = digest(JsonOutput.toJson(stagedRows).toByteArray(Charsets.UTF_8))
                    check(stagedMappingSha == asMap(asMap(manifest.getValue("modules")).getValue(module)).getValue("stagedMappingSha256"))
                    val producers = listOf<Task>(compiler) + if (metadata) listOf(tasks.getByName("allMetadataJar")) else emptyList()
                    producers.forEach { producer ->
                        val state = producer.state
                        check(state.executed && producer.enabled && !state.noSource && state.failure == null &&
                            state.skipMessage in listOf(null, "UP-TO-DATE", "FROM-CACHE")) { "Missing real MaterialIcons producer execution: ${producer.path}" }
                        check(records(producer.outputs.files.files.flatMap(::leaves)).any { (it.getValue("size") as Long) > 0L }) {
                            "MaterialIcons compiler output is empty: ${producer.path}"
                        }
                    }
                    evidence("$module-$stage", mapOf("fingerprint" to fingerprint, "module" to module, "stage" to stage,
                        "compilerType" to compiler.javaClass.name, "sourceCount" to sources.size, "sourceSetSha256" to sourceSetSha,
                        "stagedMappingSha256" to stagedMappingSha,
                        "sourceManifest" to records(listOf(manifestFile)).single(),
                        "compilerPlugins" to records(compiler.compilerPluginClasspath?.files.orEmpty()),
                        "compilerPluginOptions" to compiler.compilerPluginCommandLine,
                        "directDependencies" to compiler.taskDependencies.getDependencies(compiler).map { it.path }.sorted(),
                        "producers" to producers.map { mapOf("task" to it.path, "skipMessage" to it.state.skipMessage,
                            "outputs" to records(it.outputs.files.files.flatMap(::leaves))) },
                        "configurations" to resolution(child), "runtime" to "NOT_RUN"))
                }
            }
        }
        recordStage("recordIconsMetadata", "compileCommonMainKotlinMetadata", "metadata", true)
        recordStage("recordIconsX64", "compileKotlinOhosX64", "native-x64", false)
        recordStage("recordIconsArm64", "compileKotlinOhosArm64", "native-arm64", false)
    }
    plugins.withId("maven-publish") {
        extensions.configure<PublishingExtension> {
            repositories { maven { name = "Port"; url = uri(repository) } }
            publications.withType<MavenPublication>().configureEach {
                artifact(rootProject.file("legal/LICENSE")) { classifier = "license"; extension = "txt" }
                artifact(rootProject.file("legal/origins.json")) { classifier = "upstream-origins"; extension = "json" }
                artifact(work.resolve("build-provenance.json")) { classifier = "build-provenance"; extension = "json" }
                if (name == "kotlinMultiplatform") {
                    artifact(rootProject.file("vendor/$module/$module-1.7.3-sources.jar")) { classifier = "upstream-sources"; extension = "jar" }
                    artifact(rootProject.file("vendor/$module/$module-1.7.3.pom")) { classifier = "upstream-pom"; extension = "xml" }
                    artifact(rootProject.file("vendor/$module/$module-1.7.3.module")) { classifier = "upstream-module"; extension = "json" }
                }
                pom {
                    name.set("Compose MaterialIcons $module")
                    description.set("Complete unmodified 1.7.3 common sources with frozen CPF OHOS dual ABI publications")
                    licenses { license { name.set(model.getValue("license").toString()); url.set(model.getValue("licenseUrl").toString()) } }
                    scm { url.set(model.getValue("repository").toString()) }
                }
            }
        }
        tasks.withType<PublishToMavenRepository>().configureEach {
            doFirst {
                check(sha(rootProject.file("legal/LICENSE")) == model.getValue("licenseSha256"))
                modules.keys.forEach { sourceModule -> listOf("metadata", "native-x64", "native-arm64").forEach { stage ->
                    val stageEvidence = readMap(work.resolve("evidence/$sourceModule-$stage.json"))
                    check(stageEvidence["fingerprint"] == fingerprint)
                    check(stageEvidence["sourceSetSha256"] == asMap(sourceInputs.getValue(sourceModule)).getValue("sourceSetSha256"))
                } }
            }
        }
        tasks.withType<Jar>().configureEach {
            isPreserveFileTimestamps = false
            isReproducibleFileOrder = true
            from(rootProject.file("legal")) { into("META-INF/licenses/material-icons") }
        }
    }
}

tasks.register("resolveIcons") {
    doLast {
        check(gradle.gradleVersion == config.getValue("gradle"))
        subprojects.forEach { child -> listOf("compileCommonMainKotlinMetadata", "allMetadataJar", "compileKotlinOhosX64",
            "compileKotlinOhosArm64", "publishAllPublicationsToPortRepository").forEach { child.tasks.getByName(it) } }
        evidence("resolve", mapOf("fingerprint" to fingerprint, "modules" to subprojects.sortedBy { it.name }.map {
            mapOf("module" to it.name, "configurations" to resolution(it))
        }))
    }
}
tasks.register("publishIcons") {
    dependsOn(subprojects.map { "${it.path}:publishAllPublicationsToPortRepository" })
}
