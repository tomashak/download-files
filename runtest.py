import oracledb
import sys
import os
import getopt
import subprocess
import atexit
import json
from robot import run, rebot
from robot.api import ExecutionResult, ResultVisitor, SuiteVisitor
from pathlib import Path

# ============================================================
# GLOBAL DEFAULT TEST TIMEOUT (override Robot "Test timeout")
# ============================================================
# Nastaví timeout pro VŠECHNY testy před spuštěním Robotu.
# Řízení přes env proměnnou ROBOT_TEST_TIMEOUT (např. "10 minutes", "900 seconds").
DEFAULT_TEST_TIMEOUT = os.getenv("ROBOT_TEST_TIMEOUT", "10 minutes")


class ForceTestTimeoutModifier(SuiteVisitor):
    """
    Nastaví timeout VŠEM testům (přepíše i existující [Timeout] v testech).
    """
    def __init__(self, timeout_value: str):
        self.timeout_value = timeout_value

    def visit_test(self, test):
        test.timeout = self.timeout_value


# Umožní import env_variables.py z resources složky
script_dir = Path(__file__).parent.resolve()
resources_dir = script_dir / "resources"
sys.path.insert(0, str(resources_dir))
from env_variables import APP_PATH, DESKTOP_FOLDER_PATH


def close_application(process_name: str):
    """
    Pokusí se ukoncit proces podle jména.
    """
    try:
        subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"{process_name} byl úspěšně uzavren.")
    except subprocess.CalledProcessError:
        print(f"Upozornení: proces {process_name} nebyl nalezen nebo se nepodarilo ukoncit.")


# Registrace atexit callbacku pro případ, že nic dalšího nezavře aplikaci
APP_PROCESS_NAME = os.path.basename(APP_PATH)


def _on_exit():
    close_application(APP_PROCESS_NAME)


atexit.register(_on_exit)


class TestStatistics(ResultVisitor):
    def __init__(self):
        self.failed = 0
        self.passed = 0

    def visit_test(self, test):
        if test.passed:
            self.passed += 1
        else:
            self.failed += 1


class MergeSuitesModifier:
    """Modifikátor pro sloucení suites."""
    def __call__(self, result):
        self.visit_suite(result.suite)
        return result

    def visit_suite(self, suite):
        merged = {}
        for subsuite in suite.suites:
            if subsuite.name in merged:
                merged_suite = merged[subsuite.name]
                merged_suite.tests.extend(subsuite.tests)
                merged_suite.suites.extend(subsuite.suites)
            else:
                merged[subsuite.name] = subsuite
        suite.suites = list(merged.values())

        new_suites = []
        for subsuite in suite.suites:
            self.visit_suite(subsuite)
            if subsuite.name == suite.name:
                suite.tests.extend(subsuite.tests)
                new_suites.extend(subsuite.suites)
            else:
                new_suites.append(subsuite)
        suite.suites = new_suites


def run_robot_for_rows(rows, robotFiles, resultDir, output_files, uid_prefix=""):
    """
    Spuštění Robot testu pro nactené řádky (ATID, INDATAID, ...).
    Používá stejnou logiku jako hlavní větve, jen je zabalena do funkce.
    """
    for idx, (atID, inDataID, outDataID, expResult, loginID, extID, name, testCaseId, bookForm) in enumerate(rows):
        uid = f"{uid_prefix}{atID}_{idx}" if uid_prefix else f"{atID}_{idx}"
        vars = [
            f'inDataID:{inDataID}',
            f'login_id:{loginID}',
            f'extId:{extID}',
            f'expResult:{expResult}',
            f'name:{name}',
            f'testCaseId:{testCaseId}',
            f'bookForm:{bookForm}',
        ] + ([f'outDataID:{outDataID}'] if outDataID else [])
        print(f"Variables for test {atID}: {vars}")

        out = f"output_{uid}.xml"
        log = f"log_{uid}.html"
        rep = f"report_{uid}.html"

        run(
            *robotFiles,
            variable=vars,
            output=out,
            log=log,
            report=rep,
            outputdir=resultDir,
            include=atID,
            settag=[f"EXTID_{extID}"],
            prerunmodifier=ForceTestTimeoutModifier(DEFAULT_TEST_TIMEOUT)
        )

        path = os.path.join(resultDir, out)
        res = ExecutionResult(path)
        stats = TestStatistics()
        res.visit(stats)
        print(f"Test {atID} - Failed: {stats.failed}, Total: {stats.passed + stats.failed}")

        if stats.failed > 0:
            print(f"Test {atID} selhal, zavírám aplikaci pred dalším testem.")
            close_application(APP_PROCESS_NAME)

        output_files.append(path)


def close_via_flaui():
    """
    Docasne spustí malou Robot Framework suite pres FlaUILibrary,
    která se pripojí k bežící aplikaci a zavre ji ciste pomocí Close Application.
    """
    from robot.api import TestSuite

    suite = TestSuite('CloseApp')
    suite.resource.imports.library('FlaUILibrary')
    test = suite.tests.create('DetachAndClose')
    test.keywords.create('Attach Application By Name', args=[APP_PROCESS_NAME])
    test.keywords.create('Close Application')
    suite.run(outputdir=resultDir)


def main():
    resultDir = 'results'

    try:
        oracleAdminDir = os.environ.get("TNS_ADMIN")
        if oracleAdminDir is None:
            print("Variable TNS_ADMIN must be set")
            sys.exit(1)

        if not os.path.exists(resultDir):
            os.makedirs(resultDir)

        robotFiles = [str(file) for file in Path(DESKTOP_FOLDER_PATH).glob("*.robot")]
        robotFiles.append("tests")

        arguments, _ = getopt.getopt(
            sys.argv[1:], "",
            ["testcase=", "testgroup=", "runset=", "suite=", "testplan=", "dbrecovery=", "help"]
        )
        if not arguments:
            print("No arguments.\nUse --help")
            sys.exit(1)

        dbrecovery = False
        for opt, value in arguments:
            if opt == "--dbrecovery":
                dbrecovery = value.lower() in ["true", "1", "yes"]

        output_files = []

        if dbrecovery:
            print("Spouštím DBRECOVERY test...")
            run(
                *robotFiles,
                output="output_dbrecovery.xml",
                log="log_dbrecovery.html",
                report="report_dbrecovery.html",
                outputdir=resultDir,
                include="DBRECOVERY",
                prerunmodifier=ForceTestTimeoutModifier(DEFAULT_TEST_TIMEOUT)
            )
            output_files.append(os.path.join(resultDir, "output_dbrecovery.xml"))

        oracledb.init_oracle_client(config_dir=oracleAdminDir)

        with open("db_credentials.json") as f:
            creds = json.load(f)

        for currentArgument, currentValue in arguments:
            if currentArgument == "--help":
                print("Usage: testLoader [options]\n")
                print("Options:")
                print("  --help                              Displays help on commandline")
                print("  --testcase <id>                     Run testcase <id>")
                print("  --testgroup <id>                    Run group of tests <id>")
                print("  --runset <id>                       Run tests from runset <id>")
                print("  --suite <id>                        Run sequence of runsets from suite <id>")
                print("  --testplan <id>                     Run test plan <id> (mix testcase/group/runset/suite)")
                print("  --dbrecovery <true/false>           Run DBRECOVERY test before tests if true\n")
                sys.exit(0)

            if currentArgument in ["--testcase", "--testgroup", "--runset"]:
                with oracledb.connect(user=creds["user"], password=creds["password"], dsn=creds["dsn"]) as connection:
                    with connection.cursor() as cursor:
                        if currentArgument == "--testcase":
                            selectStr = (
                                f"select TC.ATID, TC.INDATAID, TC.OUTDATAID, TC.EXPRESULT, TR.LOGINID, TC.EXTID, TC.NAME, TC.TESTCASEID, TC.BOOKFORM "
                                f"from isfodata.art_testcase TC, isfodata.art_role TR "
                                f"where TC.ROLEID = TR.ID and TC.TESTCASEID = {currentValue}"
                            )
                        elif currentArgument == "--testgroup":
                            cursor.execute(
                                f"select OBJECTID, SUBOBJECTID, TESTAREAID from isfodata.art_testcasegroup TCG where TCG.TESTCASEGROUPID = {currentValue}"
                            )
                            group = cursor.fetchone()
                            if not group:
                                print(f"Testgroup id {currentValue} not found.")
                                sys.exit(1)
                            objectid, subobjectid, testareaid = group
                            strs = [
                                "and TCG.OBJECTID = TC.OBJECTID" if objectid else "",
                                "and TCG.SUBOBJECTID = TC.SUBOBJECTID" if subobjectid else "",
                                "and TCG.TESTAREAID = TC.TESTAREAID" if testareaid else ""
                            ]
                            selectStr = (
                                "select TC.ATID, TC.INDATAID, TC.OUTDATAID, TC.EXPRESULT, TR.LOGINID, TC.EXTID, TC.NAME, TC.TESTCASEID, TC.BOOKFORM\n"
                                "from isfodata.art_testcase TC, isfodata.art_role TR, isfodata.art_testcasegroup TCG\n"
                                "where TC.ROLEID = TR.ID\n" + "\n".join(strs) + "\n"
                                "and TCG.TYPEOFTESTID = TC.TYPEOFTEST\n"
                                f"and TCG.TESTCASEGROUPID = {currentValue}\n"
                                "ORDER BY tc.tcorder ASC"
                            )
                        elif currentArgument == "--runset":
                            selectStr = (
                                "select TC.ATID, TC.INDATAID, TC.OUTDATAID, TC.EXPRESULT, "
                                "       TR.LOGINID, TC.EXTID, TC.NAME, TC.TESTCASEID, TC.BOOKFORM\n"
                                "from   isfodata.art_runset_test RST,\n"
                                "       isfodata.art_testcase TC,\n"
                                "       isfodata.art_role TR\n"
                                "where  TC.ROLEID = TR.ID\n"
                                "  and  RST.TESTCASE_ID = TC.TESTCASEID\n"
                                f"  and  RST.RUNSET_ID = {currentValue}\n"
                                "order by RST.SEQ_NO ASC"
                            )

                        print(selectStr)
                        cursor.execute(selectStr)
                        rows = cursor.fetchall()
                        if not rows:
                            print(f"Id {currentValue} not found")
                            sys.exit(1)

                        for idx, (atID, inDataID, outDataID, expResult, loginID, extID, name, testCaseId, bookForm) in enumerate(rows):
                            uid = f"{atID}_{idx}"
                            vars = [
                                f'inDataID:{inDataID}',
                                f'login_id:{loginID}',
                                f'extId:{extID}',
                                f'expResult:{expResult}',
                                f'name:{name}',
                                f'testCaseId:{testCaseId}',
                                f'bookForm:{bookForm}',
                            ] + ([f'outDataID:{outDataID}'] if outDataID else [])
                            print(f"Variables for test {atID}: {vars}")

                            out = f"output_{uid}.xml"
                            log = f"log_{uid}.html"
                            rep = f"report_{uid}.html"

                            run(
                                *robotFiles,
                                variable=vars,
                                output=out,
                                log=log,
                                report=rep,
                                outputdir=resultDir,
                                include=atID,
                                settag=[f"EXTID_{extID}"],
                                prerunmodifier=ForceTestTimeoutModifier(DEFAULT_TEST_TIMEOUT)
                            )

                            path = os.path.join(resultDir, out)
                            res = ExecutionResult(path)
                            stats = TestStatistics()
                            res.visit(stats)
                            print(f"Test {atID} - Failed: {stats.failed}, Total: {stats.passed + stats.failed}")

                            if stats.failed > 0:
                                print(f"Test {atID} selhal, zavírám aplikaci pred dalším testem.")
                                close_application(APP_PROCESS_NAME)

                            output_files.append(path)

            elif currentArgument == "--suite":
                with oracledb.connect(user=creds["user"], password=creds["password"], dsn=creds["dsn"]) as connection:
                    with connection.cursor() as cursor:
                        selectRunsets = (
                            "SELECT SEQ_NO, RUNSET_ID "
                            "FROM isfodata.art_runset_suite_item "
                            f"WHERE SUITE_ID = {currentValue} "
                            "ORDER BY SEQ_NO ASC"
                        )
                        print(selectRunsets)
                        cursor.execute(selectRunsets)
                        runsets = cursor.fetchall()
                        if not runsets:
                            print(f"Suite ID {currentValue} not found or has no runsets.")
                            sys.exit(1)

                        for suiteSeq, runset_id in runsets:
                            print(f"\n=== Spouštím Runset {runset_id} (poradí v suite {suiteSeq}) ===")
                            subquery = (
                                "select TC.ATID, TC.INDATAID, TC.OUTDATAID, TC.EXPRESULT, "
                                "       TR.LOGINID, TC.EXTID, TC.NAME, TC.TESTCASEID, TC.BOOKFORM\n"
                                "from   isfodata.art_runset_test RST,\n"
                                "       isfodata.art_testcase TC,\n"
                                "       isfodata.art_role TR\n"
                                "where  TC.ROLEID = TR.ID\n"
                                f"  and  RST.RUNSET_ID = {runset_id}\n"
                                "  and  RST.TESTCASE_ID = TC.TESTCASEID\n"
                                "order by RST.SEQ_NO ASC"
                            )
                            print(subquery)
                            cursor.execute(subquery)
                            rows = cursor.fetchall()
                            if not rows:
                                print(f"Runset {runset_id} neobsahuje žádné testy, pokracuju na další.")
                                continue

                            for idx, (atID, inDataID, outDataID, expResult, loginID, extID, name, testCaseId, bookForm) in enumerate(rows):
                                uid = f"{atID}_S{suiteSeq}_R{runset_id}_{idx}"
                                vars = [
                                    f'inDataID:{inDataID}',
                                    f'login_id:{loginID}',
                                    f'extId:{extID}',
                                    f'expResult:{expResult}',
                                    f'name:{name}',
                                    f'testCaseId:{testCaseId}',
                                    f'bookForm:{bookForm}',
                                ] + ([f'outDataID:{outDataID}'] if outDataID else [])
                                print(f"Variables for test {atID}: {vars}")

                                out = f"output_{uid}.xml"
                                log = f"log_{uid}.html"
                                rep = f"report_{uid}.html"

                                run(
                                    *robotFiles,
                                    variable=vars,
                                    output=out,
                                    log=log,
                                    report=rep,
                                    outputdir=resultDir,
                                    include=atID,
                                    settag=[f"EXTID_{extID}"],
                                    prerunmodifier=ForceTestTimeoutModifier(DEFAULT_TEST_TIMEOUT)
                                )

                                path = os.path.join(resultDir, out)
                                res = ExecutionResult(path)
                                stats = TestStatistics()
                                res.visit(stats)
                                print(f"Test {atID} - Failed: {stats.failed}, Total: {stats.passed + stats.failed}")

                                if stats.failed > 0:
                                    print(f"Test {atID} selhal, zavírám aplikaci pred dalším testem.")
                                    close_application(APP_PROCESS_NAME)

                                output_files.append(path)

            elif currentArgument == "--testplan":
                with oracledb.connect(user=creds["user"], password=creds["password"], dsn=creds["dsn"]) as connection:
                    with connection.cursor() as cursor:
                        selectPlan = (
                            "SELECT SEQ_NO, ITEM_TYPE, ITEM_ID "
                            "FROM isfodata.art_testplan_item "
                            f"WHERE TESTPLAN_ID = {currentValue} "
                            "ORDER BY SEQ_NO ASC"
                        )
                        print(selectPlan)
                        cursor.execute(selectPlan)
                        items = cursor.fetchall()
                        if not items:
                            print(f"Testplan ID {currentValue} not found or has no items.")
                            sys.exit(1)

                        for seq_no, item_type, item_id in items:
                            item_type_upper = item_type.upper()
                            print(f"\n=== TestPlan {currentValue}: položka {seq_no} – {item_type_upper} {item_id} ===")

                            if item_type_upper == "TESTCASE":
                                selectStr = (
                                    "select TC.ATID, TC.INDATAID, TC.OUTDATAID, TC.EXPRESULT, TR.LOGINID, TC.EXTID, TC.NAME, TC.TESTCASEID, TC.BOOKFORM "
                                    "from isfodata.art_testcase TC, isfodata.art_role TR "
                                    f"where TC.ROLEID = TR.ID and TC.TESTCASEID = {item_id}"
                                )
                                print(selectStr)
                                cursor.execute(selectStr)
                                rows = cursor.fetchall()
                                if not rows:
                                    print(f"  -> TESTCASE {item_id} has no rows, skipping.")
                                    continue

                                run_robot_for_rows(
                                    rows, robotFiles, resultDir, output_files,
                                    uid_prefix=f"TP{currentValue}_SEQ{seq_no}_TC_"
                                )

                            elif item_type_upper == "TESTGROUP":
                                cursor.execute(
                                    f"select OBJECTID, SUBOBJECTID, TESTAREAID from isfodata.art_testcasegroup TCG where TCG.TESTCASEGROUPID = {item_id}"
                                )
                                group = cursor.fetchone()
                                if not group:
                                    print(f"  -> TESTGROUP {item_id} not found, skipping.")
                                    continue
                                objectid, subobjectid, testareaid = group
                                strs = [
                                    "and TCG.OBJECTID = TC.OBJECTID" if objectid else "",
                                    "and TCG.SUBOBJECTID = TC.SUBOBJECTID" if subobjectid else "",
                                    "and TCG.TESTAREAID = TC.TESTAREAID" if testareaid else ""
                                ]
                                selectStr = (
                                    "select TC.ATID, TC.INDATAID, TC.OUTDATAID, TC.EXPRESULT, TR.LOGINID, TC.EXTID, TC.NAME, TC.TESTCASEID, TC.BOOKFORM\n"
                                    "from isfodata.art_testcase TC, isfodata.art_role TR, isfodata.art_testcasegroup TCG\n"
                                    "where TC.ROLEID = TR.ID\n" + "\n".join(strs) + "\n"
                                    "and TCG.TYPEOFTESTID = TC.TYPEOFTEST\n"
                                    f"and TCG.TESTCASEGROUPID = {item_id}\n"
                                    "ORDER BY tc.tcorder ASC"
                                )
                                print(selectStr)
                                cursor.execute(selectStr)
                                rows = cursor.fetchall()
                                if not rows:
                                    print(f"  -> TESTGROUP {item_id} has no rows, skipping.")
                                    continue

                                run_robot_for_rows(
                                    rows, robotFiles, resultDir, output_files,
                                    uid_prefix=f"TP{currentValue}_SEQ{seq_no}_TG_"
                                )

                            elif item_type_upper == "RUNSET":
                                selectStr = (
                                    "select TC.ATID, TC.INDATAID, TC.OUTDATAID, TC.EXPRESULT, "
                                    "       TR.LOGINID, TC.EXTID, TC.NAME, TC.TESTCASEID, TC.BOOKFORM\n"
                                    "from   isfodata.art_runset_test RST,\n"
                                    "       isfodata.art_testcase TC,\n"
                                    "       isfodata.art_role TR\n"
                                    "where  TC.ROLEID = TR.ID\n"
                                    "  and  RST.TESTCASE_ID = TC.TESTCASEID\n"
                                    f"  and  RST.RUNSET_ID = {item_id}\n"
                                    "order by RST.SEQ_NO ASC"
                                )
                                print(selectStr)
                                cursor.execute(selectStr)
                                rows = cursor.fetchall()
                                if not rows:
                                    print(f"  -> RUNSET {item_id} has no rows, skipping.")
                                    continue

                                run_robot_for_rows(
                                    rows, robotFiles, resultDir, output_files,
                                    uid_prefix=f"TP{currentValue}_SEQ{seq_no}_RS_"
                                )

                            elif item_type_upper == "SUITE":
                                selectRunsets = (
                                    "SELECT SEQ_NO, RUNSET_ID "
                                    "FROM isfodata.art_runset_suite_item "
                                    f"WHERE SUITE_ID = {item_id} "
                                    "ORDER BY SEQ_NO ASC"
                                )
                                print(selectRunsets)
                                cursor.execute(selectRunsets)
                                runsets = cursor.fetchall()
                                if not runsets:
                                    print(f"  -> SUITE {item_id} has no runsets, skipping.")
                                    continue

                                for suiteSeq, runset_id in runsets:
                                    print(f"    -> Spouštím Runset {runset_id} (v suite {item_id}, poradí {suiteSeq})")
                                    subquery = (
                                        "select TC.ATID, TC.INDATAID, TC.OUTDATAID, TC.EXPRESULT, "
                                        "       TR.LOGINID, TC.EXTID, TC.NAME, TC.TESTCASEID, TC.BOOKFORM\n"
                                        "from   isfodata.art_runset_test RST,\n"
                                        "       isfodata.art_testcase TC,\n"
                                        "       isfodata.art_role TR\n"
                                        "where  TC.ROLEID = TR.ID\n"
                                        f"  and  RST.RUNSET_ID = {runset_id}\n"
                                        "  and  RST.TESTCASE_ID = TC.TESTCASEID\n"
                                        "order by RST.SEQ_NO ASC"
                                    )
                                    print(subquery)
                                    cursor.execute(subquery)
                                    rows = cursor.fetchall()
                                    if not rows:
                                        print(f"      -> RUNSET {runset_id} has no rows, skipping.")
                                        continue

                                    run_robot_for_rows(
                                        rows, robotFiles, resultDir, output_files,
                                        uid_prefix=f"TP{currentValue}_SEQ{seq_no}_SU{item_id}_RS{runset_id}_S{suiteSeq}_"
                                    )

                            else:
                                print(f"  -> Unknown ITEM_TYPE '{item_type}', skipping.")
                                continue

        if output_files:
            merged_xml = os.path.join(resultDir, "output.xml")
            merged_log = os.path.join(resultDir, "log.html")
            merged_rep = os.path.join(resultDir, "report.html")
            rebot(
                *output_files,
                output="output.xml",
                log="log.html",
                report="report.html",
                outputdir=resultDir,
                prerebotmodifier=MergeSuitesModifier()
            )
            print("Merged results generated:")
            print(f"  XML: {merged_xml}")
            print(f"  Log: {merged_log}")
            print(f"  Report: {merged_rep}")

    except getopt.error as err:
        print(err)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()