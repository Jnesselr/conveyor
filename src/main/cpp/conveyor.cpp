// vim:cindent:cino=\:0:et:fenc=utf-8:ff=unix:sw=4:ts=4:

#include <QUuid>
#include <QDebug>
#include <QScopedPointer>
#include <QTimer>

#include <conveyor/address.h>
#include <conveyor/conveyor.h>

#include "conveyorprivate.h"
#include "jobprivate.h"
#include "printerprivate.h"

namespace conveyor
{
    Conveyor *
    Conveyor::connectToDaemon (Address const * address)
    {
        return ConveyorPrivate::connect (address);
    }

    Conveyor::Conveyor
        ( Connection * const connection
        , ConnectionStream * const connectionStream
        , JsonRpc * const jsonRpc
        , ConnectionThread * const connectionThread
        )
        : m_private
            ( new ConveyorPrivate
                ( this
                , connection
                , connectionStream
                , jsonRpc
                , connectionThread
                )
            )
    {
    }

    Conveyor::~Conveyor (void)
    {
    }

    const QList<Printer *>& Conveyor::printers()
    {
        return m_private->printers();
    }

    QList<Job *> const &
    Conveyor::jobs (void)
    {
        return m_private->m_jobs;
    }
}
