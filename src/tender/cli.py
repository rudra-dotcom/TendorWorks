import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="tender")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the web application")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("ingest", help="Index new and changed source files in database/")
    db = commands.add_parser("db", help="Database migrations")
    db.add_argument("action", choices=["upgrade", "current", "revision"])
    db.add_argument("--message", default="model change")
    evaluation_report = commands.add_parser(
        "evaluation-report", help="Regenerate a revision evaluation workbook"
    )
    evaluation_report.add_argument("revision_id")
    drafts = commands.add_parser(
        "draft-packs", help="Create review-only candidate packs from eligible PDF files"
    )
    drafts.add_argument(
        "--rebuild", type=Path, help="Rebuild a draft pack using approved rows from this review XLSX"
    )
    drafts.add_argument("--pack", type=Path, help="Draft .pack.json used with --rebuild")
    commands.add_parser("schema", help="Print the domain package JSON schema")
    demo = commands.add_parser("demo-package", help="Write a synthetic example domain package")
    demo.add_argument("path", type=Path)
    evaluate = commands.add_parser(
        "evaluate", help="Run reference cases without modifying authoritative data"
    )
    evaluate.add_argument("cases", type=Path)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("tender.app:create_app", factory=True, host=args.host, port=args.port)
    elif args.command == "schema":
        from tender.schemas import DomainPack

        print(json.dumps(DomainPack.model_json_schema(), indent=2))
    elif args.command == "demo-package":
        from tender.demo import demo_pack

        args.path.parent.mkdir(parents=True, exist_ok=True)
        args.path.write_text(demo_pack().model_dump_json(indent=2))
        print(f"Synthetic example written to {args.path}")
    else:
        if args.command == "db":
            from alembic.config import Config

            from alembic import command
            from tender.config import Settings

            cfg = Config("alembic.ini")
            cfg.set_main_option("script_location", str(Path("alembic").resolve()))
            cfg.set_main_option("sqlalchemy.url", Settings().database_url)
            if args.action == "upgrade":
                command.upgrade(cfg, "head")
            elif args.action == "current":
                command.current(cfg)
            else:
                command.revision(cfg, message=args.message, autogenerate=True)
            return
        from tender.config import Settings
        from tender.db import Repository
        from tender.ingestion import FolderIngestor
        from tender.knowledge import KnowledgeGateway
        from tender.storage import ObjectStore

        settings = Settings()
        repo = Repository(settings)
        gateway = KnowledgeGateway(repo, ObjectStore(settings), settings)
        ingestor = FolderIngestor(gateway)
        if args.command == "ingest":
            print(json.dumps(ingestor.scan(), indent=2))
        elif args.command == "draft-packs":
            if args.rebuild:
                if not args.pack:
                    parser.error("draft-packs --rebuild requires --pack")
                print(ingestor.drafts.rebuild_approved(args.rebuild, args.pack))
            else:
                print(
                    json.dumps(
                        {"drafts": ingestor.draft_files(), "message": "NVIDIA chat must be configured."},
                        indent=2,
                    )
                )
        elif args.command == "evaluation-report":
            from tender.evaluation_reports import write_evaluation_workbook
            from tender.schemas import EstimateResult

            row = repo.get_revision(args.revision_id, settings.database_tenant)
            print(write_evaluation_workbook(EstimateResult.model_validate(row.result), settings.outputs_dir))
        else:
            from tender.evaluation import evaluate_cases

            report = evaluate_cases(args.cases, gateway, ingestor)
            print(json.dumps(report, indent=2))
            if not report["passed"]:
                repo.engine.dispose()
                raise SystemExit(1)
        repo.engine.dispose()


if __name__ == "__main__":
    main()
