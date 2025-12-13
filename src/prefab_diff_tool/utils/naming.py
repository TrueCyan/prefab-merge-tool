"""
Unity-style naming utilities.

Provides functions to convert Unity internal property names to human-readable
display names, similar to Unity's ObjectNames.NicifyVariableName().
"""

import re
from functools import lru_cache


@lru_cache(maxsize=1024)
def nicify_variable_name(name: str) -> str:
    """
    Convert a Unity variable name to a nice display name.

    This mimics Unity's ObjectNames.NicifyVariableName() behavior:
    - Removes common prefixes (m_, k_, s_, _)
    - Converts camelCase and PascalCase to spaced words
    - Preserves acronyms (GPU, UI, etc.)
    - Handles special Unity property names

    Examples:
        m_LocalPosition -> Local Position
        m_LocalScale -> Local Scale
        m_RootOrder -> Root Order
        isKinematic -> Is Kinematic
        m_GameObject -> Game Object
        m_Father -> Father
        m_Children -> Children
        useGravity -> Use Gravity
        m_Mass -> Mass
        m_LinearVelocity -> Linear Velocity
        m_AngularVelocity -> Angular Velocity
        m_Enabled -> Enabled
        serializedVersion -> Serialized Version
        m_PrefabInstance -> Prefab Instance
        m_PrefabAsset -> Prefab Asset
        m_Script -> Script
        m_Name -> Name
        m_EditorHideFlags -> Editor Hide Flags
        m_EditorClassIdentifier -> Editor Class Identifier
        m_LocalRotation -> Local Rotation
        m_AnchoredPosition -> Anchored Position
        m_SizeDelta -> Size Delta
        m_Pivot -> Pivot
        m_AnchorMin -> Anchor Min
        m_AnchorMax -> Anchor Max

    Args:
        name: The internal property name (e.g., "m_LocalPosition")

    Returns:
        The nicified display name (e.g., "Local Position")
    """
    if not name:
        return ""

    original = name

    # Remove common prefixes: m_, k_, s_, _
    prefixes = ("m_", "k_", "s_", "_")
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # Handle empty result after prefix removal
    if not name:
        return original

    # Special case: all uppercase (like "ID", "GUID", "UI")
    if name.isupper() and len(name) <= 4:
        return name

    # Insert spaces before uppercase letters and handle special cases
    result = []
    prev_char = None
    prev_was_upper = False
    prev_was_digit = False

    for i, char in enumerate(name):
        is_upper = char.isupper()
        is_digit = char.isdigit()

        # Determine if we need a space before this character
        need_space = False

        if i > 0:
            # Space before uppercase following lowercase: "localPosition" -> "local Position"
            if is_upper and prev_char and prev_char.islower():
                need_space = True
            # Space before uppercase that starts a new word in acronyms: "XMLParser" -> "XML Parser"
            elif is_upper and prev_was_upper:
                # Look ahead to see if this starts a new word
                if i + 1 < len(name) and name[i + 1].islower():
                    need_space = True
            # Space before digit following letter: "Vector3" -> "Vector 3" (optional, Unity doesn't always do this)
            # elif is_digit and prev_char and prev_char.isalpha():
            #     need_space = True
            # Space before letter following digit: "3D" -> keep as "3D"
            # No space needed

        if need_space and result:
            result.append(" ")

        # Capitalize first character
        if i == 0:
            result.append(char.upper())
        else:
            result.append(char)

        prev_char = char
        prev_was_upper = is_upper
        prev_was_digit = is_digit

    return "".join(result)


def get_property_path_parts(path: str) -> list[str]:
    """
    Split a Unity property path into parts.

    Examples:
        "m_LocalPosition.x" -> ["m_LocalPosition", "x"]
        "m_Children.Array.data[0]" -> ["m_Children", "Array", "data[0]"]

    Args:
        path: The property path

    Returns:
        List of path parts
    """
    return path.split(".")


def nicify_property_path(path: str) -> str:
    """
    Convert a full property path to a nice display string.

    Examples:
        "m_LocalPosition.x" -> "Local Position > X"
        "m_Children.Array.data[0]" -> "Children > Array > data[0]"

    Args:
        path: The property path

    Returns:
        Nicified path string
    """
    parts = get_property_path_parts(path)
    nicified = [nicify_variable_name(part) for part in parts]
    return " > ".join(nicified)


def get_property_display_name(path: str) -> str:
    """
    Get just the last part of a property path, nicified.

    Examples:
        "m_LocalPosition.x" -> "X"
        "m_LocalPosition" -> "Local Position"

    Args:
        path: The property path

    Returns:
        Nicified display name for the leaf property
    """
    parts = get_property_path_parts(path)
    if parts:
        return nicify_variable_name(parts[-1])
    return ""


# Component type display names
COMPONENT_DISPLAY_NAMES = {
    "Transform": "Transform",
    "RectTransform": "Rect Transform",
    "MonoBehaviour": "Script",
    "MeshRenderer": "Mesh Renderer",
    "MeshFilter": "Mesh Filter",
    "SkinnedMeshRenderer": "Skinned Mesh Renderer",
    "BoxCollider": "Box Collider",
    "SphereCollider": "Sphere Collider",
    "CapsuleCollider": "Capsule Collider",
    "MeshCollider": "Mesh Collider",
    "Rigidbody": "Rigidbody",
    "Rigidbody2D": "Rigidbody 2D",
    "Camera": "Camera",
    "Light": "Light",
    "AudioSource": "Audio Source",
    "AudioListener": "Audio Listener",
    "Animator": "Animator",
    "Animation": "Animation",
    "Canvas": "Canvas",
    "CanvasRenderer": "Canvas Renderer",
    "CanvasScaler": "Canvas Scaler",
    "GraphicRaycaster": "Graphic Raycaster",
    "Image": "Image",
    "Text": "Text",
    "Button": "Button",
    "InputField": "Input Field",
    "Slider": "Slider",
    "Toggle": "Toggle",
    "Scrollbar": "Scrollbar",
    "ScrollRect": "Scroll Rect",
    "ParticleSystem": "Particle System",
    "ParticleSystemRenderer": "Particle System Renderer",
    "TrailRenderer": "Trail Renderer",
    "LineRenderer": "Line Renderer",
    "SpriteRenderer": "Sprite Renderer",
    "TextMesh": "Text Mesh",
    "TextMeshPro": "TextMeshPro",
    "TextMeshProUGUI": "TextMeshPro - Text (UI)",
    "TMP_Text": "TextMeshPro Text",
    "NavMeshAgent": "Nav Mesh Agent",
    "NavMeshObstacle": "Nav Mesh Obstacle",
    "CharacterController": "Character Controller",
    "Collider2D": "Collider 2D",
    "BoxCollider2D": "Box Collider 2D",
    "CircleCollider2D": "Circle Collider 2D",
    "PolygonCollider2D": "Polygon Collider 2D",
    "EdgeCollider2D": "Edge Collider 2D",
    "CompositeCollider2D": "Composite Collider 2D",
    "SpriteShapeRenderer": "Sprite Shape Renderer",
    "SortingGroup": "Sorting Group",
    "SpriteMask": "Sprite Mask",
    "LayoutGroup": "Layout Group",
    "HorizontalLayoutGroup": "Horizontal Layout Group",
    "VerticalLayoutGroup": "Vertical Layout Group",
    "GridLayoutGroup": "Grid Layout Group",
    "ContentSizeFitter": "Content Size Fitter",
    "AspectRatioFitter": "Aspect Ratio Fitter",
    "RawImage": "Raw Image",
    "Mask": "Mask",
    "RectMask2D": "Rect Mask 2D",
    "EventSystem": "Event System",
    "EventTrigger": "Event Trigger",
}


def get_component_display_name(type_name: str, script_name: str | None = None) -> str:
    """
    Get display name for a component type.

    Args:
        type_name: The component type name (e.g., "MonoBehaviour")
        script_name: Optional script name for MonoBehaviour components

    Returns:
        Display name for the component
    """
    if type_name == "MonoBehaviour" and script_name:
        # For MonoBehaviour, use the script name with nicification
        return nicify_variable_name(script_name)

    return COMPONENT_DISPLAY_NAMES.get(type_name, nicify_variable_name(type_name))


# Property groupings for better organization
TRANSFORM_PROPERTIES = {
    "m_LocalPosition": "Position",
    "m_LocalRotation": "Rotation",
    "m_LocalScale": "Scale",
    "m_LocalEulerAnglesHint": "Rotation (Euler)",
}

RECT_TRANSFORM_PROPERTIES = {
    "m_AnchoredPosition": "Anchored Position",
    "m_SizeDelta": "Size Delta",
    "m_Pivot": "Pivot",
    "m_AnchorMin": "Anchor Min",
    "m_AnchorMax": "Anchor Max",
}
