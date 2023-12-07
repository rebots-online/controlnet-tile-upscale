import torch
import os
from typing import List
import numpy as np
import shutil
import time
from cog import BasePredictor, Input, Path
from diffusers.utils import load_image
from diffusers import (
    StableDiffusionControlNetImg2ImgPipeline,
    ControlNetModel,
    StableDiffusionPipeline,
    DDIMScheduler,
    DPMSolverMultistepScheduler,
    EulerAncestralDiscreteScheduler,
    EulerDiscreteScheduler,
)
from Pillow import Image

SCHEDULERS = {
    "DDIM": DDIMScheduler,
    "DPMSolverMultistep": DPMSolverMultistepScheduler,
    "K_EULER_ANCESTRAL": EulerAncestralDiscreteScheduler,
    "K_EULER": EulerDiscreteScheduler,
}

SD15_WEIGHTS = "weights"
CONTROLNET_CACHE = "controlnet-cache"


class Predictor(BasePredictor):
    def setup(self):
        """Load the model into memory to make running multiple predictions efficient"""

        print("Loading pipeline...")
        st = time.time()

        controlnet = ControlNetModel.from_pretrained(
            CONTROLNET_CACHE,
            torch_dtype=torch.float16
        )

        self.pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
            SD15_WEIGHTS,
            torch_dtype=torch.float16,
            controlnet=controlnet
        ).to("cuda")

        print("Setup complete in %f" % (time.time() - st))

    def resize_for_condition_image(self, input_image, resolution):
        input_image = input_image.convert("RGB")
        W, H = input_image.size
        k = float(resolution) / min(H, W)
        H *= k
        W *= k
        H = int(round(H / 64.0)) * 64
        W = int(round(W / 64.0)) * 64
        img = input_image.resize((W, H), resample=Image.LANCZOS)
        return img

    def load_image(self, path):
        shutil.copyfile(path, "/tmp/image.png")
        return load_image("/tmp/image.png").convert("RGB")

    @torch.inference_mode()
    def predict(
        self,
        prompt: str = Input(description="Prompt for the model"),
        image: Path = Input(
            description="Control image for scribble controlnet", default=None
        ),
        conditioning_scale: float = Input(
            description="Conditioning scale for controlnet",
            default=0.5,
            ge=0,
            le=1,
        ),
        strength: float = Input(
            description="Denoising strength. 1 means total destruction of the original image",
            default=0.5,
            ge=0,
            le=1,
        ),
        scheduler: str = Input(
            default="DDIM",
            choices=SCHEDULERS.keys(),
            description="Choose a scheduler.",
        ),
        steps: int = Input(
            description="Steps", default=20
        ),
        guidance_scale: float = Input(
            description="Scale for classifier-free guidance",
            default=7.0,
            ge=0.1,
            le=30.0,
        ),
        seed: int = Input(
            description="Seed", default=None
        ),
        negative_prompt: str = Input(  # FIXME
            description="Negative prompt",
            default="Longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality",
        ),
        guess_mode: bool = Input(
            description="In this mode, the ControlNet encoder will try best to recognize the content of the input image even if you remove all prompts. The `guidance_scale` between 3.0 and 5.0 is recommended.",
            default=False,
        ),
    ) -> List[Path]:

        self.pipe.scheduler = SCHEDULERS[scheduler].from_config(self.pipe.scheduler.config)
        generator = torch.Generator("cuda").manual_seed(seed)
        loaded_image = self.load_image(image)
        control_image = self.resize_for_condition_image(loaded_image)

        args = {
            "prompt": prompt,
            "image": loaded_image,
            "control_image": control_image,
            "strength": strength,
            "controlnet_conditioning_scale": conditioning_scale,
            "negative_prompt": negative_prompt,
            "guidance_scale": guidance_scale,
            "generator": generator,
            "num_inference_steps": steps,
            "guess_mode": guess_mode,
        }

        outputs = self.pipe(**args)
        output_paths = []
        for i, sample in enumerate(outputs.images):
            output_path = f"/tmp/out-{i}.png"
            sample.save(output_path)
            output_paths.append(Path(output_path))
        return output_paths
