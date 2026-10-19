<script lang="ts">
	import { onMount } from 'svelte';
	import * as THREE from 'three';
	import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
	import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

	/**
	 * Turntable view of one exported hotspot model (details/<hotspot>/model.glb).
	 * Models are in metres, Y-up, centred and resting on y = 0, facing +Z.
	 */
	let { src, label }: { src: string; label: string } = $props();

	let container: HTMLDivElement;
	let canvas: HTMLCanvasElement;
	let status: 'loading' | 'ready' | 'error' = $state('loading');
	let interacted = $state(false);

	/** Soft radial blob under the model: reads as ambient occlusion where it meets the ground. */
	function blobTexture() {
		const size = 128;
		const c = document.createElement('canvas');
		c.width = c.height = size;
		const ctx = c.getContext('2d')!;
		const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
		g.addColorStop(0, 'rgba(0,0,0,0.55)');
		g.addColorStop(0.45, 'rgba(0,0,0,0.22)');
		g.addColorStop(1, 'rgba(0,0,0,0)');
		ctx.fillStyle = g;
		ctx.fillRect(0, 0, size, size);
		const tex = new THREE.CanvasTexture(c);
		tex.colorSpace = THREE.SRGBColorSpace;
		return tex;
	}

	function disposeObject(root: THREE.Object3D) {
		root.traverse((obj) => {
			const mesh = obj as THREE.Mesh;
			if (!mesh.isMesh) return;
			mesh.geometry?.dispose();
			const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
			for (const mat of mats) {
				if (!mat) continue;
				for (const value of Object.values(mat)) {
					if (value && (value as THREE.Texture).isTexture) (value as THREE.Texture).dispose();
				}
				mat.dispose();
			}
		});
	}

	onMount(() => {
		let disposed = false;
		const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.outputColorSpace = THREE.SRGBColorSpace;
		renderer.toneMapping = THREE.NeutralToneMapping;
		renderer.toneMappingExposure = 1.0;
		renderer.shadowMap.enabled = true;
		renderer.shadowMap.type = THREE.PCFSoftShadowMap;

		const scene = new THREE.Scene();
		const pmrem = new THREE.PMREMGenerator(renderer);
		const room = new RoomEnvironment();
		const envMap = pmrem.fromScene(room, 0.04).texture;
		room.dispose();
		scene.environment = envMap;
		scene.environmentIntensity = 0.9;

		const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 50);
		const controls = new OrbitControls(camera, canvas);
		controls.enableDamping = true;
		controls.dampingFactor = 0.08;
		controls.enablePan = false;
		controls.autoRotate = true;
		controls.autoRotateSpeed = 0.9;
		controls.maxPolarAngle = Math.PI * 0.53;
		const stopAutoRotate = () => {
			controls.autoRotate = false;
			interacted = true;
		};
		controls.addEventListener('start', stopAutoRotate);

		// a gentle key light for shape and a soft shadow on an invisible floor
		const key = new THREE.DirectionalLight(0xffffff, 1.1);
		key.castShadow = true;
		key.shadow.mapSize.set(1024, 1024);
		key.shadow.radius = 6;
		key.shadow.bias = -0.0005;
		scene.add(key, key.target);

		const shadowFloor = new THREE.Mesh(
			new THREE.PlaneGeometry(1, 1),
			new THREE.ShadowMaterial({ opacity: 0.16 })
		);
		shadowFloor.rotation.x = -Math.PI / 2;
		shadowFloor.receiveShadow = true;
		scene.add(shadowFloor);

		const blob = new THREE.Mesh(
			new THREE.PlaneGeometry(1, 1),
			new THREE.MeshBasicMaterial({ map: blobTexture(), transparent: true, depthWrite: false })
		);
		blob.rotation.x = -Math.PI / 2;
		blob.position.y = 0.0005;
		blob.renderOrder = -1;
		scene.add(blob);

		let model: THREE.Object3D | undefined;

		new GLTFLoader().load(
			src,
			(gltf) => {
				if (disposed) {
					disposeObject(gltf.scene);
					return;
				}
				model = gltf.scene;
				model.traverse((obj) => {
					if ((obj as THREE.Mesh).isMesh) obj.castShadow = obj.receiveShadow = true;
				});
				scene.add(model);

				const box = new THREE.Box3().setFromObject(model);
				const size = box.getSize(new THREE.Vector3());
				const center = box.getCenter(new THREE.Vector3());
				const radius = box.getBoundingSphere(new THREE.Sphere()).radius;

				const footprint = Math.max(size.x, size.z);
				blob.scale.set(size.x * 1.5 + 0.04, size.z * 1.5 + 0.04, 1);
				shadowFloor.scale.setScalar(footprint * 4 + radius * 2);

				key.position.set(center.x + radius * 0.6, box.max.y + radius * 4, center.z + radius * 0.9);
				key.target.position.copy(center).setY(0);
				const cam = key.shadow.camera;
				const extent = radius * 2.2;
				cam.left = cam.bottom = -extent;
				cam.right = cam.top = extent;
				cam.near = 0.01;
				cam.far = radius * 10;
				cam.updateProjectionMatrix();

				const fov = THREE.MathUtils.degToRad(camera.fov);
				const distance = (radius / Math.sin(fov / 2)) * 0.9;
				const yaw = THREE.MathUtils.degToRad(-32);
				camera.position.set(
					center.x + Math.sin(yaw) * distance * 0.95,
					center.y + distance * 0.3,
					center.z + Math.cos(yaw) * distance * 0.95
				);
				camera.near = distance / 100;
				camera.far = distance * 20;
				camera.updateProjectionMatrix();
				controls.target.copy(center);
				controls.minDistance = radius * 1.1;
				controls.maxDistance = distance * 2.5;
				controls.update();
				status = 'ready';
			},
			undefined,
			(err) => {
				console.error(`Couldn't load model ${src}`, err);
				if (!disposed) status = 'error';
			}
		);

		const resize = () => {
			const { clientWidth: w, clientHeight: h } = container;
			if (!w || !h) return;
			renderer.setSize(w, h, false);
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
		};
		const observer = new ResizeObserver(resize);
		observer.observe(container);
		resize();

		renderer.setAnimationLoop(() => {
			controls.update();
			renderer.render(scene, camera);
		});

		return () => {
			disposed = true;
			renderer.setAnimationLoop(null);
			observer.disconnect();
			controls.removeEventListener('start', stopAutoRotate);
			controls.dispose();
			if (model) disposeObject(model);
			disposeObject(blob);
			disposeObject(shadowFloor);
			key.shadow.map?.dispose();
			envMap.dispose();
			pmrem.dispose();
			renderer.dispose();
			renderer.forceContextLoss();
		};
	});
</script>

<div class="viewer" bind:this={container}>
	<canvas bind:this={canvas} aria-label="3D model of {label}. Drag to turn it, scroll or pinch to zoom."
	></canvas>
	{#if status === 'loading'}
		<div class="status"><span class="spinner" aria-hidden="true"></span>Loading model</div>
	{:else if status === 'error'}
		<div class="status">The 3D model couldn't be loaded.</div>
	{:else if !interacted}
		<div class="hint">Drag to turn · scroll to zoom</div>
	{/if}
</div>

<style>
	.viewer {
		position: relative;
		width: 100%;
		height: 100%;
		background:
			radial-gradient(ellipse 70% 60% at 50% 42%, rgba(244, 241, 234, 0.16), transparent 70%),
			linear-gradient(#2a2926, #191917);
		overflow: hidden;
	}
	canvas {
		display: block;
		width: 100%;
		height: 100%;
		cursor: grab;
		touch-action: none;
		outline: none;
	}
	canvas:active {
		cursor: grabbing;
	}
	.status,
	.hint {
		position: absolute;
		left: 0;
		right: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		font-size: 12px;
		letter-spacing: 0.04em;
		color: var(--ink-faint);
		pointer-events: none;
	}
	.status {
		inset: 0;
	}
	.hint {
		bottom: 12px;
		animation: fade-in 600ms 400ms ease both;
	}
	.spinner {
		width: 14px;
		height: 14px;
		border-radius: 50%;
		border: 1.5px solid var(--line);
		border-top-color: var(--accent);
		animation: spin 900ms linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@keyframes fade-in {
		from {
			opacity: 0;
		}
	}
</style>
