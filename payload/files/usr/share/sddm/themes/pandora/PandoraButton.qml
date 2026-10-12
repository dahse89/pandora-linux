import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    required property var theme
    property bool primary: false

    implicitHeight: 44
    font.family: "Noto Sans"
    font.pixelSize: 14
    font.weight: Font.DemiBold
    hoverEnabled: true
    Accessible.name: text

    contentItem: Text {
        text: control.text
        font: control.font
        color: control.primary ? control.theme.base : control.theme.foreground
        opacity: control.enabled ? 1 : 0.5
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        textFormat: Text.PlainText
    }
    background: Rectangle {
        radius: 10
        color: control.primary
            ? (control.down ? "#78aae9" : control.hovered ? "#b7d6ff" : control.theme.accent)
            : (control.down || control.hovered ? control.theme.field : "transparent")
        opacity: control.enabled ? 1 : 0.5
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? control.theme.foreground
            : control.primary ? "transparent" : control.theme.outline
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
}
