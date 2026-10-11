import typer

from omneum import initialization
from omneum.paths import get_config_dir

app = typer.Typer()
network_app = typer.Typer(help='Account-authenticated Network enrollment and credential lifecycle.')
app.add_typer(network_app, name='network')


@network_app.command('enroll')
def network_enroll():
    _network_manage('enroll')


@network_app.command('renew')
def network_renew():
    _network_manage('renew')


@network_app.command('rotate')
def network_rotate():
    _network_manage('rotate')


@network_app.command('revoke')
def network_revoke():
    _network_manage('revoke')


@network_app.command('withdraw')
def network_withdraw():
    _network_manage('withdraw')


@network_app.command('status')
def network_status():
    _network_manage('status')


def _network_manage(action):
    from .onboarding import manage
    try:
        manage(action, typer.echo, typer.confirm)
    except Exception:
        typer.echo('Network account operation failed. Check production provisioning, account authorization, '
                   'consent and private storage. If enrollment or rotation was uncertain, use renew with '
                   'the same account and installation. Local evaluation remains available.', err=True)
        raise typer.Exit(1) from None


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
