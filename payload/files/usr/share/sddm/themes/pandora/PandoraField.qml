import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: control
    required property var theme

    implicitHeight: 48
    leftPadding: 14
    rightPadding: 14
    font.family: "Noto Sans"
    font.pixelSize: 15
    color: theme.foreground
    placeholderTextColor: theme.secondary
    selectionColor: theme.accent
    selectedTextColor: theme.base
    selectByMouse: true
    persistentSelection: false
    background: Rectangle {
        radius: 10
        color: control.theme.field
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.theme.accent : control.theme.outline
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
}
