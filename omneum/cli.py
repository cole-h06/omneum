import typer

from omneum import initialization
from omneum.paths import get_config_dir

app = typer.Typer()


@app.callback()
def main() -> None:
    """Omneum command-line interface."""
    pass


@app.command()
def init(public_key_hex: str | None = typer.Option(None, help="Expected daemon public key in hex.")) -> None:
    """Initialize an Omneum deployment."""
    try:
        config = initialization.initialize(public_key_hex)
    except initialization.InitializationError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    if config is None:
        typer.echo("Omneum is already initialized.")
    else:
        typer.echo("Omneum initialized.")
        typer.echo(f"Deployment: {config.deployment_id}")
    typer.echo(f"Configuration: {get_config_dir()}")


@app.command()
def install() -> None:
    """Install the exact-version protected daemon and initialize Omneum."""
    from omneum.installation import InstallError, run_install

    try:
        run_install(typer.echo)
    except InstallError as error:
        typer.echo(f"Installation failed: {error}", err=True)
        raise typer.Exit(1) from None
    except OSError:
        typer.echo("Installation failed: unable to access required files or system tools. "
                   "Check permissions and available disk space, then retry.", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
