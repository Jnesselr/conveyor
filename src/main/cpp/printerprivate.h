// vim:cindent:cino=\:0:et:fenc=utf-8:ff=unix:sw=4:ts=4:

#ifndef PRINTERPRIVATE_H
#define PRINTERPRIVATE_H

#include <conveyor.h>
#include <QStringList>

namespace conveyor
{
    class SlicerConfiguration;

    class PrinterPrivate
    {
    public:
        PrinterPrivate
            ( Conveyor * conveyor
            , Printer * printer
            , QString const & uniqueName
            );

        Job * print (QString const & inputFile
                     , const SlicerConfiguration & slicer_conf
                     , QString const & material
                     , bool const skipStartEnd);
        Job * printToFile
            ( QString const & inputFile
            , QString const & outputFile
            , const SlicerConfiguration & slicer_conf
            , QString const & material
            , bool const skipStartEnd
            );
        Job * slice
            ( QString const & inputFile
            , QString const & outputFile
            , const SlicerConfiguration & slicer_conf
            , QString const & material
            );

        void updateFromJson (Json::Value const &);

        Conveyor * const m_conveyor;
        Printer * const m_printer;
        QString m_displayName;
        QString m_uniqueName;
        QString m_printerType;
        QStringList m_machineNames;
        bool m_canPrint;
        bool m_canPrintToFile;
        bool m_hasHeatedPlatform;
        int m_numberOfToolheads;
        ToolTemperature m_toolTemperature;
        ConnectionStatus m_connectionStatus;
        float m_buildVolumeXmin;
        float m_buildVolumeYmin;
        float m_buildVolumeZmin;
        float m_buildVolumeXmax;
        float m_buildVolumeYmax;
        float m_buildVolumeZmax;
    };
}

#endif
