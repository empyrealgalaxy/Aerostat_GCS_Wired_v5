#!/usr/bin/env python3
"""Generate management PDF: Aerostat GCS End-to-End Data Process."""

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = r"d:\2026\Aerostate Project Phase 2\docs\Aerostat_GCS_End_to_End_Data_Process.pdf"


def _table(data, col_widths=None):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def build():
    doc = SimpleDocTemplate(
        OUTPUT,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Aerostat GCS End-to-End Data Process",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#1a5276"),
        spaceAfter=6,
        alignment=TA_CENTER,
    )
    subtitle = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#566573"),
        spaceAfter=14,
        alignment=TA_CENTER,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=colors.HexColor("#1a5276"),
        spaceBefore=14,
        spaceAfter=8,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        spaceAfter=8,
    )
    bullet = ParagraphStyle(
        "Bullet",
        parent=body,
        leftIndent=14,
        bulletIndent=0,
        spaceAfter=4,
    )

    story = []
    story.append(Paragraph("Aerostat GCS Dashboard", title))
    story.append(Paragraph("End-to-End Data Process", title))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Document for Management Review", subtitle))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a5276")))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Purpose", h2))
    story.append(
        Paragraph(
            "This document describes the complete end-to-end <b>data process</b> of the Aerostat "
            "Ground Control Station (GCS) software — from device connection to live monitoring, "
            "logging, and report export.",
            body,
        )
    )

    story.append(Paragraph("End-to-End Process Overview", h2))
    story.append(
        _table(
            [
                ["Step", "Stage", "Input", "Output"],
                ["1", "Connect device", "IP/Port or COM settings", "Live data link"],
                ["2", "Parse & map data", "Raw CSV from device", "Named telemetry"],
                ["3", "Display live", "Mapped parameters", "Real-time dashboard"],
                ["4", "Monitor alerts", "Threshold limits", "Warnings if out of range"],
                ["5", "Log automatically", "All updates", "data.json audit file"],
                ["6", "Export reports", "Date range + format", "CSV / JSON / TXT file"],
                ["7", "Deploy / reuse", "Windows executable", "Field-ready GCS tool"],
            ],
            col_widths=[1.2 * cm, 3.5 * cm, 5 * cm, 5.5 * cm],
        )
    )
    story.append(Spacer(1, 10))

    # Step 1
    story.append(Paragraph("Step 1 — Connect to the Device", h2))
    story.append(
        _table(
            [
                ["Action", "Detail"],
                ["Launch software", "Run dashboard on GCS laptop (AerostateDashboard.exe)"],
                ["Choose connection", "Ethernet/TCP (IP + Port) or COM/Serial (Port + Baud rate)"],
                ["Connect", "Admin → Device → Connect; status shows Connected, lines received"],
                ["Verify", "Dashboard parameters begin updating within seconds"],
            ],
            col_widths=[4 * cm, 12.5 * cm],
        )
    )
    story.append(Spacer(1, 8))

    # Step 2 - live parameters
    story.append(Paragraph("Step 2 — Receive & Process Device Data", h2))
    story.append(
        Paragraph(
            "The device sends CSV sensor data over Ethernet or COM. The dashboard automatically "
            "parses, maps, and stores each update for display and logging.",
            body,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        _table(
            [
                ["Category", "Parameters received from device"],
                ["Environmental", "Ambient temperature, ambient pressure, humidity"],
                ["Pressures", "Helium pressure, pressure difference (ΔP)"],
                ["Temperatures", "Helium temperature, ground (DHT) temperature"],
                ["Position", "Altitude (AMSL & AGL), latitude, longitude, pitch, roll, heading, compass"],
                ["Wind & Tether", "Wind speed, confluence point tension (C.P. Tension)"],
                ["System", "Ping / response time"],
            ],
            col_widths=[3.5 * cm, 13 * cm],
        )
    )
    story.append(Spacer(1, 8))

    # Step 3
    story.append(Paragraph("Step 3 — Live Monitoring on Dashboard", h2))
    story.append(
        _table(
            [
                ["Capability", "Description"],
                ["Live values", "All connected parameters update automatically on screen"],
                ["Organized sections", "Atmospheric, Pressures, Temperatures, Position, Wind, Tether"],
                ["Charts", "Trend graphs for key parameters over time"],
                ["Timestamp", "Last update time visible for operational awareness"],
                ["Admin control", "Admin can choose which parameters operators see"],
            ],
            col_widths=[4 * cm, 12.5 * cm],
        )
    )
    story.append(Spacer(1, 8))

    # Step 4
    story.append(Paragraph("Step 4 — Alerts & Threshold Monitoring", h2))
    story.append(
        _table(
            [
                ["Action", "Detail"],
                ["Set limits", "Admin defines min/max thresholds per parameter"],
                ["Monitor", "System continuously compares live values to limits"],
                ["Alert", "Notification shown when a parameter goes out of range"],
                ["Smart alerts", "Only visible parameters receiving live device data trigger alerts"],
            ],
            col_widths=[4 * cm, 12.5 * cm],
        )
    )
    story.append(Spacer(1, 8))

    # Step 5 & 6
    story.append(Paragraph("Step 5 — Automatic Data Logging", h2))
    story.append(
        Paragraph(
            "Every sensor update is saved to <b>data.json</b> with date, time, source "
            "(ethernet or COM), all parameter values, and change details. Logging runs "
            "continuously while the device is connected.",
            body,
        )
    )
    story.append(Paragraph("Step 6 — Export & Reporting", h2))
    story.append(
        _table(
            [
                ["Action", "Detail"],
                ["Open Logs", "Use Logs button on dashboard; select date range"],
                ["Choose format", "CSV, JSON, or TXT"],
                ["Download", "File ready for Excel, analysis, or archival"],
                ["Source tagging", "Each record tagged as ethernet or com:COMx"],
            ],
            col_widths=[4 * cm, 12.5 * cm],
        )
    )
    story.append(Spacer(1, 12))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 8))
    summary = ParagraphStyle(
        "Summary",
        parent=body,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1a5276"),
        backColor=colors.HexColor("#eaf2f8"),
        borderPadding=10,
        spaceAfter=8,
    )
    story.append(
        Paragraph(
            "<b>Summary:</b> We have developed an end-to-end GCS data system. The operator connects "
            "the aerostat device over Ethernet or COM, the dashboard displays live telemetry with "
            "alerts, all data is logged automatically, and reports can be exported for management "
            "and analysis — delivered as deployable Windows software.",
            summary,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<i>Scope: Data acquisition, live display, alerting, logging, and export.</i>",
            ParagraphStyle("Foot", parent=body, fontSize=8, textColor=colors.grey),
        )
    )

    doc.build(story)
    print(f"Created: {OUTPUT}")


if __name__ == "__main__":
    build()
