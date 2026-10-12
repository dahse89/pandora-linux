pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: control
    required property var theme

    implicitHeight: 44
    leftPadding: 14
    rightPadding: 36
    font.family: "Noto Sans"
    font.pixelSize: 14
    hoverEnabled: true

    contentItem: Text {
        text: control.displayText
        font: control.font
        color: control.theme.foreground
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        textFormat: Text.PlainText
    }
    indicator: Canvas {
        x: control.width - width - 14
        y: (control.height - height) / 2
        width: 10
        height: 6
        onPaint: {
            const ctx = getContext("2d");
            ctx.clearRect(0, 0, width, height);
            ctx.strokeStyle = control.theme.secondary;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(1, 1);
            ctx.lineTo(5, 5);
            ctx.lineTo(9, 1);
            ctx.stroke();
        }
    }
    background: Rectangle {
        radius: 10
        color: control.theme.field
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? control.theme.accent : control.theme.outline
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
    delegate: ItemDelegate {
        id: option
        required property int index
        width: control.width
        height: 44
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: control.textAt(option.index)
            font: control.font
            color: control.theme.foreground
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }
        background: Rectangle {
            radius: 6
            color: option.highlighted ? control.theme.field : "transparent"
        }
    }
    popup: Popup {
        y: control.height + 4
        width: control.width
        padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 220)
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle {
            radius: 10
            color: control.theme.panel
            border.color: control.theme.outline
        }
    }
}
