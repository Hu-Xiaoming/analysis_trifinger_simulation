import pathlib

import pybullet

import trifinger_simulation


def import_mesh(
    mesh_file_path,
    position,
    orientation=[0, 0, 0, 1],
    is_concave=False,
    color_rgba=None,
    pybullet_client_id=None,
):
    """
    Create a collision object based on a mesh file.

    Args:
        mesh_file_path:  Path to the mesh file.
        position:  Position (x, y, z) of the object.
        orientation:  Quaternion defining the orientation of the object.
        is_concave:  If set to true, the object is loaded as concav shape.
            Only use this for static objects.
        color_rgba:  Optional colour of the object given as a list of RGBA
            values in the interval [0, 1].  If not specified, pyBullet
            assigns a random colour.

    Returns:
        The created object.
    """
    if is_concave:
        flags = pybullet.GEOM_FORCE_CONCAVE_TRIMESH
    else:
        flags = 0

    object_id = pybullet.createCollisionShape(
        shapeType=pybullet.GEOM_MESH,
        fileName=mesh_file_path,
        flags=flags,
        physicsClientId=pybullet_client_id,
    )

    obj = pybullet.createMultiBody(
        baseCollisionShapeIndex=object_id,
        baseVisualShapeIndex=-1,
        basePosition=position,
        baseOrientation=orientation,
        physicsClientId=pybullet_client_id,
    )

    # set colour
    if color_rgba is not None:
        pybullet.changeVisualShape(
            obj,
            -1,
            rgbaColor=color_rgba,
            physicsClientId=pybullet_client_id,
        )

    return obj


class BaseCollisionObject:
    """A cuboid which can be interacted with.

    This class only provides the set/get_state methods but doesn't actually
    load any object.  So don't use this directly but use one of its child
    classes.

    Note that child classes must define an attribute ``_object_id`` with the id
    of the object.
    """

    def __init__(
        self,
        pybullet_client_id=0,
    ):
        """
        Args:
            pybullet_client_id:  Optional ID of the pybullet client.
        """
        self._pybullet_client_id = pybullet_client_id

    def set_state(self, position, orientation):
        """
        Resets the object to the provided position and orientation

        Args:
            position: New position.
            orientation: New orientation.
        """
        pybullet.resetBasePositionAndOrientation(
            self._object_id,
            position,
            orientation,
            physicsClientId=self._pybullet_client_id,
        )

    def get_state(self):
        """
        Returns:
            Current position and orientation of the object.
        """
        position, orientation = pybullet.getBasePositionAndOrientation(
            self._object_id,
            physicsClientId=self._pybullet_client_id,
        )
        return list(position), list(orientation)

    def __del__(self):
        """
        Removes the object from the environment.
        """
        # At this point it may be that pybullet was already shut down. To avoid
        # an error, only remove the object if the simulation is still running.
        if pybullet.isConnected(self._pybullet_client_id):
            pybullet.removeBody(self._object_id, self._pybullet_client_id)


class Cuboid(BaseCollisionObject):
    """A cuboid which can be interacted with."""

    def __init__(
        self,
        position,
        orientation,
        half_extents,
        mass,
        color_rgba=None,
        pybullet_client_id=0,
    ):
        """
        Create a new cuboid.

        Args:
            position (list): Initial xyz-position of the cuboid.
            orientation (list): Initial orientation quaternion (x, y, z, w) of
                the cuboid.
            half_extents (list): Half-extends of the cuboid in x/y/z-direction.
            mass (float): Mass of the cuboid in kg.  Set to 0 for a static
                object.
            color_rgba: Optional tuple of RGBA colour.
            pybullet_client_id:  Optional ID of the pybullet client.
        """
        super().__init__(pybullet_client_id)

        self.block_id = pybullet.createCollisionShape(
            shapeType=pybullet.GEOM_BOX,
            halfExtents=half_extents,
            physicsClientId=self._pybullet_client_id,
        )

        # only create a visual shape if a colour was specified
        if color_rgba is not None:
            self.visual_shape_id = pybullet.createVisualShape(
                shapeType=pybullet.GEOM_BOX,
                halfExtents=half_extents,
                rgbaColor=color_rgba,
                physicsClientId=self._pybullet_client_id,
            )
        else:
            self.visual_shape_id = -1

        self._object_id = pybullet.createMultiBody(
            baseCollisionShapeIndex=self.block_id,
            baseVisualShapeIndex=self.visual_shape_id,
            basePosition=position,
            baseOrientation=orientation,
            baseMass=mass,
            physicsClientId=self._pybullet_client_id,
        )

        # set dynamics of the block
        lateral_friction = 1
        spinning_friction = 0.001
        restitution = 0
        pybullet.changeDynamics(
            bodyUniqueId=self._object_id,
            linkIndex=-1,
            lateralFriction=lateral_friction,
            spinningFriction=spinning_friction,
            restitution=restitution,
            physicsClientId=self._pybullet_client_id,
        )


class Cube(Cuboid):
    """A cube object."""

    def __init__(
        self,
        position=[0.15, 0.0, 0.0425],
        orientation=[0, 0, 0, 1],
        half_width=0.0325,
        mass=0.08,
        color_rgba=None,
        pybullet_client_id=0,
    ):
        super().__init__(
            position,
            orientation,
            [half_width] * 3,
            mass,
            color_rgba=color_rgba,
            pybullet_client_id=pybullet_client_id,
        )


# For backward compatibility
Block = Cube


class ColoredCubeV2(BaseCollisionObject):
    """Model of the colored "Cube v2"."""

    def __init__(
        self,
        position=(0, 0, 0),
        orientation=(0, 0, 0, 1),
        pybullet_client_id=0,
    ):
        """Load a Cube v2 object.

        Args:
            position: Position at which the cube is spawned.
            orientation: Orientation with which the cube is spawned.
            pybullet_client_id:  Optional ID of the pybullet client.
        """
        self._pybullet_client_id = pybullet_client_id

        cube_urdf_file = (
            pathlib.Path(trifinger_simulation.__file__).parent
            / "data/cube_v2/cube_v2.urdf"
        )
        self._object_id = pybullet.loadURDF(
            fileName=str(cube_urdf_file),
            basePosition=position,
            baseOrientation=orientation,
            physicsClientId=pybullet_client_id,
        )
