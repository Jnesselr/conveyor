#ifndef PRINTERLIST_TEST_CASE_H
#define PRINTERLIST_TEST_CASE_H

#include <cppunit/extensions/HelperMacros.h>

#include <conveyor/conveyor.h>

class PrinterListTestCase : public CPPUNIT_NS::TestFixture
{
    CPPUNIT_TEST_SUITE(PrinterListTestCase);
	
	CPPUNIT_TEST(sampleTest);
	CPPUNIT_TEST(otherTest);

	CPPUNIT_TEST_SUITE_END();

public:

    void setUp();

    void printersConnectedTest();

    conveyor::Conveyor * m_conveyor;
};

#endif