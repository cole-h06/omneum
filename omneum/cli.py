import typer

from omneum.deployment import DeploymentConfig, save_config
from omneum.paths import get_config_dir, get_key_dir
from omneum.provision import generate_deployment_id
from omneum.keys import generate_voprf_key_material, encode_public_key

app = typer.Typer()


@app.callback()
def main() -> None:
    """Omneum command-line interface."""
    pass


@app.command()
def init() -> None:
    """Initialize an Omneum deployment."""
    config_dir = get_config_dir()
    key_dir = get_key_dir()

    if (config_dir / "config.toml").exists():
        typer.echo("Omneum is already initialized.")
        typer.echo(f"Configuration: {config_dir}")
        typer.echo(f"Keys: {key_dir}")
        raise typer.Exit()

    deployment_id = generate_deployment_id()

    key_material = generate_voprf_key_material()

    config = DeploymentConfig(
        deployment_id=deployment_id,
        voprf_key_version=1,
        voprf_public_key=encode_public_key(
            key_material.public_key,
        ),
    )

    save_config(config)

    typer.echo("Omneum initialized.")
    typer.echo(f"Deployment: {deployment_id}")
    typer.echo(f"Configuration: {config_dir}")
    typer.echo(f"Keys: {key_dir}")


if __name__ == "__main__":
    app()