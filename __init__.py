# -*- coding: utf-8 -*-

"""
WZ Workflow Plugin
"""

def classFactory(iface):
    """
    Funkcja wywoływana przez QGIS podczas ładowania wtyczki.
    """
    from .wz_workflow_plugin import WZWorkflowPlugin
    return WZWorkflowPlugin(iface)