from qgis.core import QgsFeature
# Import bezpieczny dla iface
try:
    from qgis.utils import iface
    IFACE_AVAILABLE = True
except ImportError:
    print("UWAGA: iface nie jest dostępne")
    iface = None
    IFACE_AVAILABLE = False

warstwa = iface.activeLayer()
selected_feats = warstwa.selectedFeatures()

if len(selected_feats) < 2:
    print("❌ Zaznacz minimum dwa poligony.")
else:
    warstwa.startEditing()

    # Agreguj geometrię
    combined_geometry = selected_feats[0].geometry()
    for feat in selected_feats[1:]:
        combined_geometry = combined_geometry.combine(feat.geometry())

    # Agreguj ID_DZIALKI i NUMER_DZIALKI
    ids = [str(f["ID_DZIALKI"]) for f in selected_feats]
    numery = [str(f["NUMER_DZIALKI"]) for f in selected_feats]

    new_id = "; ".join(ids)
    new_numer = "; ".join(numery)

    # Oblicz powierzchnię
    pole_m2 = round(combined_geometry.area(), 2)

    # Utwórz nowy obiekt
    new_feat = QgsFeature(warstwa.fields())
    new_feat.setGeometry(combined_geometry)

    # Bazuj na atrybutach z pierwszego obiektu
    for field in warstwa.fields():
        name = field.name()
        if name == "ID_DZIALKI":
            new_feat[name] = new_id
        elif name == "NUMER_DZIALKI":
            new_feat[name] = new_numer
        elif name == "POLE_EWIDENCYJNE":
            new_feat[name] = pole_m2
        else:
            new_feat[name] = selected_feats[0][name]

    # Dodaj nowy obiekt i usuń stare
    warstwa.addFeature(new_feat)
    for f in selected_feats:
        warstwa.deleteFeature(f.id())

    warstwa.commitChanges()
    warstwa.triggerRepaint()
    print("✅ Zaznaczone działki zostały połączone.")
