import groovy.json.JsonSlurper

pluginManagement {
    repositories {
        maven("https://maven.eazytec-cloud.com/nexus/repository/maven-develop/")
        maven("https://maven.eazytec-cloud.com/nexus/repository/maven-public/")
        gradlePluginPortal()
        mavenCentral()
    }
    plugins {
        id("org.jetbrains.kotlin.multiplatform") version "2.4.20-0.1.0-08"
        id("org.jetbrains.kotlin.plugin.compose") version "2.4.20-0.1.0-08"
    }
}
val pins = JsonSlurper().parse(file("dependency-pins.json")) as Map<*, *>
val metadataPins = JsonSlurper().parse(file("metadata-pins.json")) as Map<*, *>
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google { content { metadataPins.forEach { (ga, version) ->
            val parts = ga.toString().split(":")
            if (parts[0].startsWith("androidx.")) includeVersion(parts[0], parts[1], version.toString())
        } } }
        maven("https://maven.eazytec-cloud.com/nexus/repository/maven-develop/") {
            content { (pins.entries + metadataPins.entries).forEach { (ga, version) ->
                val parts = ga.toString().split(":")
                includeVersion(parts[0], parts[1], version.toString())
            } }
        }
        maven("https://maven.eazytec-cloud.com/nexus/repository/maven-public/") {
            content { (pins.entries + metadataPins.entries).forEach { (ga, version) ->
                val parts = ga.toString().split(":")
                includeVersion(parts[0], parts[1], version.toString())
            } }
        }
        mavenCentral()
    }
}
rootProject.name = "material-icons-port"
include(":material-icons-core", ":material-icons-extended")
