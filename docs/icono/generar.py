"""Icono de Ahorro Batería: una batería con el símbolo del euro, en blanco
sobre un cuadrado redondeado verde.

    /tmp/hav/bin/python docs/icono/generar.py custom_components/ahorro_bateria/brand
"""
import sys

from PIL import Image, ImageDraw


def dibujar(lado: int) -> Image.Image:
    S = 4  # sobremuestreo para bordes suaves
    W = lado * S
    u = W / 256  # unidades de un lienzo de 256

    # Fondo: cuadrado redondeado con un degradado vertical suave.
    fondo = Image.new("RGBA", (W, W))
    arriba, abajo = (102, 187, 106), (27, 94, 32)
    df = ImageDraw.Draw(fondo)
    for y in range(W):
        t = y / (W - 1)
        df.line([(0, y), (W, y)], fill=tuple(round(arriba[i] + (abajo[i] - arriba[i]) * t) for i in range(3)) + (255,))
    mascara = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, W - 1, W - 1], radius=56 * u, fill=255)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    img.paste(fondo, (0, 0), mascara)

    capa = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(capa)

    # Batería vertical: cuerpo con contorno grueso y borne arriba.
    x0, y0, x1, y1 = 74 * u, 58 * u, 182 * u, 222 * u
    d.rounded_rectangle([x0, y0, x1, y1], radius=18 * u, outline=255, width=round(13 * u))
    d.rounded_rectangle([106 * u, 36 * u, 150 * u, 62 * u], radius=6 * u, fill=255)

    # Euro dentro: arco abierto a la derecha y dos barras.
    cx, cy, r, g = 140 * u, 140 * u, 34 * u, 11 * u
    d.arc([cx - r, cy - r, cx + r, cy + r], start=45, end=315, fill=255, width=round(g))
    for dy in (-11 * u, 9 * u):
        d.rounded_rectangle([cx - r - 12 * u, cy + dy - g / 2, cx + 4 * u, cy + dy + g / 2], radius=g / 2, fill=255)

    blanco = Image.new("RGBA", (W, W), (255, 255, 255, 255))
    img.paste(blanco, (0, 0), capa)
    return img.resize((lado, lado), Image.LANCZOS)


destino = sys.argv[1]
dibujar(256).save(f"{destino}/icon.png", optimize=True)
dibujar(512).save(f"{destino}/icon@2x.png", optimize=True)
print("ok")
