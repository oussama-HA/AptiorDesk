import QtQuick
import QtQuick3D

Rectangle {
    id: root
    width: 1200
    height: 760
    color: "#09090b"

    property url componentSource
    property string loadStatus: "Preparing avatar…"
    property string meetingStatus: "Listening"
    property real avatarYaw: 0
    property real cameraX: 0
    property real cameraY: 1.42
    property real cameraYaw: 0
    property real cameraPitch: 0

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#17171b" }
            GradientStop { position: 1.0; color: "#09090b" }
        }
    }

    Rectangle {
        x: 48
        y: 48
        width: 1104
        height: 664
        radius: 28
        color: "#111115"
        border.color: "#2d2d33"
        border.width: 1
    }

    View3D {
        id: view
        x: 49
        y: 49
        width: 1102
        height: 662

        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#111115"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        PerspectiveCamera {
            id: camera
            position: Qt.vector3d(root.cameraX, root.cameraY, 1.72)
            eulerRotation.x: root.cameraPitch
            eulerRotation.y: root.cameraYaw
            fieldOfView: 36
            clipNear: 0.05
            clipFar: 100
        }

        DirectionalLight {
            eulerRotation.x: -34
            eulerRotation.y: -28
            brightness: 0.8
            color: "#fff5f1"
            castsShadow: true
            shadowFactor: 55
        }

        DirectionalLight {
            eulerRotation.x: -20
            eulerRotation.y: 145
            brightness: 0.28
            color: "#ff5a61"
        }

        PointLight {
            position: Qt.vector3d(0, 2.2, 1.4)
            brightness: 2.5
            color: "#ffffff"
            quadraticFade: 4
        }

        Loader3D {
            id: avatar
            objectName: "avatarComponentLoader"
            source: root.componentSource
            eulerRotation.y: root.avatarYaw
        }
    }

    Rectangle {
        x: 78
        y: 76
        width: 250
        height: 54
        radius: 27
        color: "#d94a50"

        Row {
            anchors.centerIn: parent
            spacing: 10

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 10
                height: 10
                radius: 5
                color: "#ffffff"

                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    NumberAnimation { from: 1.0; to: 0.35; duration: 700 }
                    NumberAnimation { from: 0.35; to: 1.0; duration: 700 }
                }
            }

            Text {
                text: "AI INTERVIEWER"
                color: "#ffffff"
                font.pixelSize: 15
                font.weight: Font.DemiBold
                font.letterSpacing: 1.2
            }
        }
    }

    Rectangle {
        x: 78
        y: 620
        width: 455
        height: 68
        radius: 18
        color: "#d90f1115"
        border.color: "#38383f"

        Column {
            anchors.left: parent.left
            anchors.leftMargin: 20
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4

            Text {
                text: "Jordan · Hiring Manager"
                color: "#f7f7f8"
                font.pixelSize: 19
                font.weight: Font.DemiBold
            }

            Text {
                text: root.loadStatus
                color: "#b0afb7"
                font.pixelSize: 14
            }
        }
    }

    Rectangle {
        x: 953
        y: 628
        width: 166
        height: 52
        radius: 26
        color: "#202025"
        border.color: "#3c3c44"

        Text {
            anchors.centerIn: parent
            text: "●  " + root.meetingStatus
            color: "#f7f7f8"
            font.pixelSize: 14
            font.weight: Font.Medium
        }
    }
}
