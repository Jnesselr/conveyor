// vim:cindent:cino=\:0:et:fenc=utf-8:ff=unix:sw=4:ts=4:

#include <QMutex>
#include <QMutexLocker>
#include <QWaitCondition>

#include <json/value.h>
#include <jsonrpc.h>
#include <conveyor.h>
#include <conveyor/connection.h>

#include "connectionstream.h"
#include "connectionthread.h"
#include "conveyorprivate.h"

namespace
{
    class SynchronousCallback : public JsonRpcCallback
    {
    public:
        void response (Json::Value const & response);
        Json::Value wait (void);

    private:
        QMutex m_mutex;
        QWaitCondition m_condition;
        Json::Value m_value;
    };

    void
    SynchronousCallback::response (Json::Value const & response)
    {
        QMutexLocker locker (& this->m_mutex);
        this->m_value = response;
        this->m_condition.wakeAll ();
    }

    Json::Value
    SynchronousCallback::wait (void)
    {
        QMutexLocker locker (& this->m_mutex);
        this->m_condition.wait (& this->m_mutex);
        return this->m_value;
    }

    static
    bool
    isErrorResponse (Json::Value const & response)
    {
        bool const result
            ( Json::Value ("2.0") == response["jsonrpc"]
              and response["error"].isObject ()
              and response["error"]["code"].isNumeric ()
              and response["error"]["message"].isString ()
            );
        return result;
    }

    static
    bool
    isSuccessResponse (Json::Value const & response)
    {
        bool const result
            ( Json::Value ("2.0") == response["jsonrpc"]
              and response.isMember ("result")
            );
        return result;
    }

    static
    Json::Value
    invoke_sync
        ( JsonRpc * jsonRpc
        , std::string const & methodName
        , Json::Value const & params
        )
    {
        SynchronousCallback callback;
        jsonRpc->invoke (methodName, params, & callback);
        Json::Value const response (callback.wait ());
        if (isErrorResponse (response))
        {
            Json::Value const error (response["error"]);
            int const code (error["code"].asInt ());
            std::string const message (error["code"].asString ());
            Json::Value const data (error["data"]);
            throw JsonRpcException (code, message, data);
        }
        else
        if (not isSuccessResponse (response))
        {
            throw std::exception ();
        }
        else
        {
            Json::Value const result (response["result"]);
            return result;
        }
    }
}

namespace conveyor
{
    ConveyorPrivate *
    ConveyorPrivate::connect (Address const * const address)
    {
        Connection * const connection (address->createConnection ());
        ConnectionStream * const connectionStream
            ( new ConnectionStream (connection)
            );
        JsonRpc * const jsonRpc (new JsonRpc (connectionStream));
        ConnectionThread * const connectionThread
            ( new ConnectionThread (connection, jsonRpc)
            );
        connectionThread->start ();
        try
        {
            Json::Value const hello
                ( invoke_sync (jsonRpc, "hello", Json::Value (Json::arrayValue))
                );
            ConveyorPrivate * const private_
                ( new ConveyorPrivate
                    ( connection
                    , connectionStream
                    , jsonRpc
                    , connectionThread
                    )
                );
            return private_;
        }
        catch (...)
        {
            connectionThread->stop ();
            connectionThread->wait ();

            delete connectionThread;
            delete jsonRpc;
            delete connectionStream;
            delete connection;

            throw;
        }
    }

    ConveyorPrivate::ConveyorPrivate
        ( Connection * const connection
        , ConnectionStream * const connectionStream
        , JsonRpc * const jsonRpc
        , ConnectionThread * const connectionThread
        )
        : m_connection (connection)
        , m_connectionStream (connectionStream)
        , m_jsonRpc (jsonRpc)
        , m_connectionThread (connectionThread)
    {
    }

    ConveyorPrivate::~ConveyorPrivate (void)
    {
        this->m_connectionThread->stop ();
        this->m_connectionThread->wait ();

        delete this->m_connectionThread;
        delete this->m_jsonRpc;
        delete this->m_connectionStream;
        delete this->m_connection;
    }

    Job *
    ConveyorPrivate::print
        ( Printer * const printer
        , QString const & inputFile
        )
    {
        Json::Value params (Json::arrayValue);
        params.append(Json::Value (inputFile.toStdString ()));
        params.append(Json::Value ());
        params.append(Json::Value (false));
        Json::Value const result
            ( invoke_sync (this->m_jsonRpc, "print", params)
            );
        Job * const job (new Job (printer, "0")); // TODO: fetch id from result
        return job;
    }

    Job *
    ConveyorPrivate::printToFile
        ( Printer * const printer
        , QString const & inputFile
        , QString const & outputFile
        )
    {
        Json::Value params (Json::arrayValue);
        params.append(Json::Value (inputFile.toStdString ()));
        params.append(Json::Value (outputFile.toStdString ()));
        params.append(Json::Value ());
        params.append(Json::Value (false));
        Json::Value const result
            ( invoke_sync (this->m_jsonRpc, "printToFile", params)
            );
        Job * const job (new Job (printer, "0")); // TODO: fetch id from result
        return job;
    }

    Job *
    ConveyorPrivate::slice
        ( Printer * const printer
        , QString const & inputFile
        , QString const & outputFile
        )
    {
        Json::Value params (Json::arrayValue);
        params.append(Json::Value (inputFile.toStdString ()));
        params.append(Json::Value (outputFile.toStdString ()));
        params.append(Json::Value ());
        params.append(Json::Value (false));
        Json::Value const result
            ( invoke_sync (this->m_jsonRpc, "slice", params)
            );
        Job * const job (new Job (printer, "0")); // TODO: fetch id from result
        return job;
    }
}