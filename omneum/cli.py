import typer

from omneum.deployment import DeploymentConfig, save_config
from omneum.paths import get_config_dir
from omneum.provision import generate_deployment_id
from omneum.keys import encode_public_key
from omneum.oprf import VOPRFClient
from omneum.daemon import DaemonServerContext, get_daemon_socket, get_daemon_uid

app = typer.Typer()


@app.callback()
def main() -> None:
    """Omneum command-line interface."""
    pass


@app.command()
def init(public_key_hex: str | None = typer.Option(None, help="Expected daemon public key in hex.")) -> None:
    """Initialize an Omneum deployment."""
    config_dir = get_config_dir()

    if (config_dir / "config.toml").exists():
        typer.echo("Omneum is already initialized.")
        typer.echo(f"Configuration: {config_dir}")
        raise typer.Exit()

    deployment_id = generate_deployment_id()

    try:
        if public_key_hex is None:
            public_key = DaemonServerContext.fetch_public_key(get_daemon_socket(), get_daemon_uid())
        else:
            public_key = bytes.fromhex(public_key_hex)
            VOPRFClient(public_key)
            DaemonServerContext(get_daemon_socket(), get_daemon_uid(), public_key)
    except Exception:
        typer.echo("Unable to verify the provisioned daemon public key.", err=True)
        raise typer.Exit(1) from None

    config = DeploymentConfig(
        deployment_id=deployment_id,
        voprf_key_version=1,
        voprf_public_key=encode_public_key(
            public_key,
        ),
    )

    try:
        save_config(config)
    except FileExistsError:
        typer.echo("Omneum is already initialized.")
        raise typer.Exit() from None

    typer.echo("Omneum initialized.")
    typer.echo(f"Deployment: {deployment_id}")
    typer.echo(f"Configuration: {config_dir}")


if __name__ == "__main__":
    app()