import QtQuick
import QtQuick3D

Rectangle {
    id: root
    color: "#0d0d10"
    property url componentSource
    property string avatarState: "idle"
    property real headYaw: 0
    property real headPitch: 0
    property real headRoll: 0
    property real headVertical: 0

    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl("office-background.png")
        fillMode: Image.PreserveAspectCrop
        horizontalAlignment: Image.AlignHCenter
        verticalAlignment: Image.AlignVCenter
        smooth: true
        mipmap: true
    }

    Rectangle {
        anchors.fill: parent
        color: "#38090a0c"
    }

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }
        PerspectiveCamera {
            // Stable video-call framing: head, shoulders, folded arms, and
            // upper torso remain visible without scaling the animated model.
            position: Qt.vector3d(0, 1.48, 1.34)
            fieldOfView: 30
            clipNear: 0.05
            clipFar: 100
        }
        DirectionalLight {
            eulerRotation.x: -34
            eulerRotation.y: -28
            brightness: 0.82
            color: "#fff5f1"
        }
        DirectionalLight {
            eulerRotation.x: -20
            eulerRotation.y: 145
            brightness: 0.24
            color: "#ff5a61"
        }
        PointLight {
            position: Qt.vector3d(0, 2.2, 1.4)
            brightness: 2.2
            color: "#ffffff"
            quadraticFade: 4
        }
        Loader3D {
            objectName: "avatarComponentLoader"
            source: root.componentSource
            position.y: root.headVertical
            eulerRotation.x: root.headPitch
            eulerRotation.y: root.headYaw
            eulerRotation.z: root.headRoll
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 18
        width: stateText.width + 30
        height: 34
        radius: 17
        color: "#ddff565f"
        Text {
            id: stateText
            anchors.centerIn: parent
            text: "AI INTERVIEWER  ·  " + root.avatarState.toUpperCase()
            color: "#ffffff"
            font.pixelSize: 12
            font.weight: Font.DemiBold
            font.letterSpacing: 0.8
        }
    }
}
