#!/usr/bin/env node
/**
 * Artwork for the featured books on a shelf: a spine with the real title and author for
 * Blender to print on the shelf copy, and web-sized cover and spine images for the
 * book that flies out in the browser. Called by blender/lib/featured.py while a room
 * builds; can also be run by hand:
 *
 *   node web/scripts/book-art.mjs --books books.json --out blender/build/books/jobs-room
 *
 * books.json: [{ slug, title, author, cover, size: [thickness, height, width] (m),
 *   spine: { bg, fg, accent?, font?, weight?, upper?, bands?: [[v0, v1, colour], ...] } }]
 *   cover: path of the cover image. spine.bands: horizontal blocks of colour, v from the
 *   bottom (0) to the top (1) of the spine, e.g. a Penguin's orange ends.
 *
 * Writes <out>/<slug>/:
 *   spine.png    spine artwork, 8 px/mm (u across the spine left to right, top = top of book)
 *   spine.webp   the same, for the browser
 *   cover.webp   the cover, at most 1200 px tall
 *   art.json     { coverAspect, coverColour, spineColour }
 * The spine reads top to bottom, as English-language spines do.
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import sharp from 'sharp';

const PX_PER_M = 8000;

const { values: opt } = parseArgs({ options: { books: { type: 'string' }, out: { type: 'string' } } });
if (!opt.books || !opt.out) {
	console.error('usage: book-art.mjs --books <books.json> --out <dir>');
	process.exit(2);
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** One line of spine text, lying down, trimmed to its ink: { data, width, height }. */
async function textImage(str, { font, weight, size, colour, spacing }) {
	const w = Math.ceil(size * str.length * 1.2 + 40);
	const h = Math.ceil(size * 2);
	const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">
		<text x="10" y="${size * 1.3}" font-family="${font}" font-weight="${weight}" font-size="${size}"
			letter-spacing="${spacing}" fill="${colour}">${esc(str)}</text></svg>`;
	const { data, info } = await sharp(Buffer.from(svg)).trim({ threshold: 1 }).png().toBuffer({ resolveWithObject: true });
	return { data, width: info.width, height: info.height, top: info.trimOffsetTop ?? 0 };
}

/**
 * The spine drawn lying down (left = top of the book), then turned a quarter clockwise,
 * so letters' tops face the reader's right with the book upright. Title and author are
 * each shrunk to fit their span along the spine.
 */
async function spineImage(book, length, across) {
	const s = book.spine;
	const font = s.font ?? 'Georgia';
	const weight = s.weight ?? 'normal';
	const upper = (t) => (s.upper ? t.toUpperCase() : t);
	const bands = (s.bands ?? [])
		.map(([v0, v1, colour]) => {
			// v runs bottom to top of the book = right to left here
			const x0 = (1 - v1) * length;
			return `<rect x="${x0}" y="0" width="${(v1 - v0) * length}" height="${across}" fill="${colour}"/>`;
		})
		.join('');
	const background = `<svg xmlns="http://www.w3.org/2000/svg" width="${length}" height="${across}">
		<rect width="100%" height="100%" fill="${s.bg}"/>${bands}</svg>`;
	const size = across * (s.scale ?? 0.42);
	const lines = [
		{ str: book.spineTitle ?? book.title, span: s.titleSpan ?? [0.06, 0.6], colour: s.fg, scale: 1 },
		{ str: book.spineAuthor ?? book.author, span: s.authorSpan ?? [0.66, 0.94], colour: s.accent ?? s.fg, scale: 0.8 }
	];
	const layers = [];
	for (const line of lines) {
		const room = (line.span[1] - line.span[0]) * length;
		const style = { font, weight, colour: line.colour, size: size * line.scale, spacing: s.upper ? size * 0.08 : 0 };
		let img = await textImage(upper(line.str), style);
		if (img.width > room) {
			const k = room / img.width;
			img = await textImage(upper(line.str), { ...style, size: style.size * k, spacing: style.spacing * k });
		}
		// centred in its span along the spine, and across it (by cap height for capitals)
		const left = Math.round(line.span[0] * length + (room - img.width) / 2);
		const top = Math.round((across - img.height) / 2);
		layers.push({ input: img.data, left, top });
	}
	return sharp(Buffer.from(background)).composite(layers).png().toBuffer();
}

async function averageColour(img) {
	const { dominant } = await img.stats();
	return `#${[dominant.r, dominant.g, dominant.b].map((c) => c.toString(16).padStart(2, '0')).join('')}`;
}

const books = JSON.parse(await readFile(opt.books, 'utf8'));
for (const book of books) {
	const dir = join(opt.out, book.slug);
	await mkdir(dir, { recursive: true });
	const [t, h] = book.size;
	const length = Math.round(h * PX_PER_M);
	const across = Math.round(t * PX_PER_M);
	const spine = await sharp(await spineImage(book, length, across)).rotate(90).png().toBuffer();
	await writeFile(join(dir, 'spine.png'), spine);
	await sharp(spine).webp({ quality: 90 }).toFile(join(dir, 'spine.webp'));

	const cover = sharp(book.cover);
	const meta = await cover.metadata();
	await cover
		.clone()
		.resize({ height: Math.min(1200, meta.height), withoutEnlargement: true })
		.webp({ quality: 90 })
		.toFile(join(dir, 'cover.webp'));
	const art = {
		coverAspect: meta.width / meta.height,
		coverColour: await averageColour(cover.clone()),
		spineColour: book.spine.bg
	};
	await writeFile(join(dir, 'art.json'), JSON.stringify(art, null, 2));
	console.log(`book-art: ${book.slug}: spine ${across}x${length} px, cover ${meta.width}x${meta.height}`);
}
