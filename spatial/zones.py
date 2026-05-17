from pydantic import BaseModel, Field

Point = tuple[float, float]
Polygon = list[Point]
BBox = tuple[float, float, float, float]


class Zone(BaseModel):
    zone_id: str
    type: str = "restricted"
    polygon: list[list[float]] = Field(min_length=3)

    def points(self) -> Polygon:
        return [(float(x), float(y)) for x, y in self.polygon]


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, current in enumerate(polygon):
        xi, yi = current
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def bbox_center(bbox: BBox) -> Point:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def bbox_intersects_polygon(bbox: BBox, polygon: Polygon) -> bool:
    x1, y1, x2, y2 = bbox
    corners = [(x1, y1), (x1, y2), (x2, y1), (x2, y2), bbox_center(bbox)]
    return any(point_in_polygon(point, polygon) for point in corners)

